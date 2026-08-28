"""End-to-end pipeline: ingest -> analyze -> report. Every stage is re-runnable."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from . import db, metrics, netting, normalize, report, scoring
from .config import Config, DEFAULT_OUT
from .event_proximity import link_trades_to_events, nearest_event_by_trade
from .returns import PriceBook
from .sources import events as events_src
from .sources import prices as prices_src
from .sources import roster as roster_src
from .sources import sectors as sectors_src
from .sources import trades as trades_src
from .sources.base import ChainOutcome, SourceUnavailable, run_chain

# Owner codes as they appear on House/Senate periodic transaction reports.
# NOTE: filings identify the owner by ROLE, not by name. A spouse is disclosed
# as "SP", never as a person. Family members are therefore modelled as roles
# attached to the member's filing — the pipeline cannot name them, and does not.
OWNER_RELATION = {
    "sp": "spouse",
    "spouse": "spouse",
    "dc": "dependent_child",
    "jt": "joint",
    "joint": "joint",
    "self": "self",
    "c": "self",
    "": "self",
}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    return slug or "unknown"


def _trade_id(row: dict) -> str:
    payload = "|".join(str(row.get(k, "")) for k in (
        "person_id", "trade_date", "disclosure_date", "ticker",
        "asset_name", "side", "amount_range_text", "source"))
    return hashlib.sha1(payload.encode()).hexdigest()[:20]


# --------------------------------------------------------------------------
# Ingest
# --------------------------------------------------------------------------

def ingest(con, cfg: Config, run_id: str, *, events_csv: Path | None = None,
           local_prices_csv: Path | None = None, local_trades_csv: Path | None = None,
           resolve_sectors: bool = True, price_start: date | None = None) -> dict:
    """Populate people, trades, benchmarks, events and prices."""
    def logger(level, message, stage="ingest"):
        db.log(con, run_id, stage, level, message)

    summary: dict = {}

    # -- benchmarks -------------------------------------------------------
    bench_rows = [{"sector": sector, "benchmark_ticker": etf,
                   "is_market_proxy": etf == cfg.market_benchmark,
                   "note": "sector benchmark", "source": "config/benchmarks.yaml"}
                  for sector, etf in cfg.sector_etfs.items()]
    bench_rows.append({"sector": "__market__", "benchmark_ticker": cfg.market_benchmark,
                       "is_market_proxy": True, "note": "market benchmark",
                       "source": "config/benchmarks.yaml"})
    db.replace_table(con, "benchmarks", pd.DataFrame(bench_rows))
    logger("INFO", f"benchmarks: {len(bench_rows)} sector mappings")

    # -- roster -----------------------------------------------------------
    roster_outcome = run_chain(
        [lambda: roster_src.congress_legislators(include_historical=True)],
        ["congress-legislators"],
        lambda lvl, msg: logger(lvl, msg, "ingest:roster"),
    )
    roster_df = roster_outcome.result.data if roster_outcome.ok else pd.DataFrame()
    summary["roster"] = roster_outcome

    # -- trades -----------------------------------------------------------
    trade_sources, trade_labels = [], []
    if local_trades_csv:
        trade_sources.append(lambda: trades_src.local_csv_trades(str(local_trades_csv)))
        trade_labels.append(f"local-csv:{Path(local_trades_csv).name}")
    trade_sources += [trades_src.stock_watcher_both, trades_src.capitoltrades,
                      trades_src.quiverquant, trades_src.senate_efd,
                      trades_src.house_clerk]
    trade_labels += ["stock-watcher-bulk", "capitoltrades", "quiverquant",
                     "senate-efd", "house-clerk"]
    trade_outcome = run_chain(
        trade_sources, trade_labels,
        lambda lvl, msg: logger(lvl, msg, "ingest:trades"),
    )
    summary["trades"] = trade_outcome
    if not trade_outcome.ok:
        logger("ERROR", "no trade source produced rows; "
                        f"attempts: {trade_outcome.summary()}", "ingest:trades")
        summary["trades_ingested"] = 0
        return summary

    people_df, trades_df, notes = build_people_and_trades(
        trade_outcome.result.data, roster_df, cfg,
        source=trade_outcome.result.source,
        source_url=trade_outcome.result.source_url,
        roster_source=roster_outcome.result.source if roster_outcome.ok else None,
    )
    for note in notes:
        logger("WARN", note, "ingest:normalize")

    # -- sectors ----------------------------------------------------------
    cache_path = DEFAULT_OUT / "sector_cache.csv"
    resolver = sectors_src.load_cache(cache_path)
    if resolve_sectors:
        try:
            needs_sector = trades_df[trades_df["sector"].isna()]["ticker"]
            found, sector_notes = sectors_src.resolve_with_yfinance(
                sorted(t for t in needs_sector.dropna().unique()), resolver)
            resolver.update(found)
            sectors_src.save_cache(cache_path, resolver)
            logger("INFO", f"sector resolver: +{len(found)} tickers "
                           f"({len(sector_notes)} unresolved)", "ingest:sectors")
        except SourceUnavailable as exc:
            logger("WARN", f"sector resolver unavailable: {exc}", "ingest:sectors")

    # A sector supplied by the source is kept; only fill the gaps.
    filled_sectors, filled_sources = [], []
    for existing, ticker in zip(trades_df["sector"], trades_df["ticker"]):
        if existing:
            filled_sectors.append(existing)
            filled_sources.append("source")
            continue
        sector, origin = normalize.resolve_sector(ticker, cfg, resolver)
        filled_sectors.append(sector)
        filled_sources.append(origin)
    trades_df["sector"] = filled_sectors
    trades_df["sector_source"] = filled_sources
    unclassified = int(trades_df["sector"].isna().sum())
    if unclassified:
        logger("WARN", f"{unclassified}/{len(trades_df)} trades have no sector; "
                       f"benchmarked against fallback {cfg.default_sector_etf}",
               "ingest:sectors")

    db.replace_table(con, "people", people_df)
    db.replace_table(con, "trades", trades_df)
    logger("INFO", f"people: {len(people_df)} rows, trades: {len(trades_df)} rows")
    summary["trades_ingested"] = len(trades_df)
    summary["people_ingested"] = len(people_df)

    # -- events -----------------------------------------------------------
    if events_csv:
        event_outcome = run_chain(
            [lambda: events_src.curated_csv(events_csv, set(cfg.sector_etfs))],
            [f"curated-events:{Path(events_csv).name}"],
            lambda lvl, msg: logger(lvl, msg, "ingest:events"),
        )
        summary["events"] = event_outcome
        if event_outcome.ok:
            for note in event_outcome.result.notes:
                logger("WARN", note, "ingest:events")
            db.replace_table(con, "events", event_outcome.result.data)
            logger("INFO", f"events: {len(event_outcome.result.data)} rows")
    else:
        logger("WARN", "no event CSV supplied; event-proximity metrics will be 0",
               "ingest:events")

    # -- prices -----------------------------------------------------------
    tickers = sorted({t for t in trades_df["ticker"].dropna().unique()})
    benchmark_tickers = sorted(set(cfg.sector_etfs.values()) | {cfg.market_benchmark,
                                                               cfg.default_sector_etf})
    all_tickers = sorted(set(tickers) | set(benchmark_tickers))
    start = price_start or _earliest_trade_date(trades_df)
    end = date.today()

    price_sources, price_labels = [], []
    if local_prices_csv:
        price_sources.append(
            lambda: prices_src.local_csv_prices(str(local_prices_csv), all_tickers, start, end))
        price_labels.append(f"local-csv:{Path(local_prices_csv).name}")
    price_sources += [
        lambda: prices_src.yfinance_prices(all_tickers, start, end),
        lambda: prices_src.alpha_vantage_prices(all_tickers, start, end),
    ]
    price_labels += ["yfinance", "alphavantage"]

    price_outcome = run_chain(price_sources, price_labels,
                              lambda lvl, msg: logger(lvl, msg, "ingest:prices"))
    summary["prices"] = price_outcome
    if price_outcome.ok:
        inserted = db.upsert_prices(con, price_outcome.result.data)
        logger("INFO", f"prices: {inserted} rows for "
                       f"{price_outcome.result.data['ticker'].nunique()} tickers "
                       f"({start} to {end})", "ingest:prices")
        missing = sorted(set(all_tickers) - set(price_outcome.result.data["ticker"]))
        if missing:
            logger("WARN", f"{len(missing)} tickers had no price data, e.g. "
                           f"{missing[:8]}", "ingest:prices")
    else:
        logger("ERROR", "no price source produced rows; returns and alpha cannot "
                        f"be computed. Attempts: {price_outcome.summary()}",
               "ingest:prices")
    return summary


def _earliest_trade_date(trades_df: pd.DataFrame) -> date:
    dates = pd.to_datetime(trades_df["trade_date"], errors="coerce").dropna()
    if dates.empty:
        return date(2012, 1, 1)          # STOCK Act took effect in 2012
    return (dates.min() - pd.Timedelta(days=10)).date()


def build_people_and_trades(raw: pd.DataFrame, roster: pd.DataFrame, cfg: Config,
                            source: str, source_url: str,
                            roster_source: str | None = None
                            ) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Normalise raw disclosure rows into the `people` and `trades` schemas."""
    notes: list[str] = []
    roster_ix: dict[str, dict] = {}
    if roster is not None and not roster.empty:
        for row in roster.to_dict("records"):
            roster_ix.setdefault(slugify(row["full_name"]), row)

    people: dict[str, dict] = {}
    trades: list[dict] = []
    unmatched_filers: set[str] = set()
    dropped_no_date = 0

    for raw_row in raw.to_dict("records"):
        filer = raw_row.get("filer_name")
        if not filer or pd.isna(filer):
            continue
        member_slug = slugify(filer)
        member_meta = roster_ix.get(member_slug)
        if member_meta is None:
            unmatched_filers.add(str(filer))

        member_id = _ensure_person(
            people, member_slug, filer, "self", None, member_meta,
            raw_row.get("chamber"), source, source_url, roster_source)

        owner_raw = str(raw_row.get("owner_code") or "").strip().lower()
        relation = OWNER_RELATION.get(owner_raw, "other_relative" if owner_raw else "self")
        if relation == "self":
            person_id = member_id
        else:
            person_id = f"{member_id}::{relation}"
            _ensure_person(
                people, person_id,
                f"{filer} ({relation.replace('_', ' ')})", relation, member_id,
                member_meta, raw_row.get("chamber"), source, source_url,
                roster_source)

        trade_date = normalize.parse_date(raw_row.get("trade_date"))
        disclosure_date = normalize.parse_date(raw_row.get("disclosure_date"))
        if trade_date is None:
            dropped_no_date += 1
            continue

        amount = normalize.parse_amount_range(raw_row.get("amount_range_text"), cfg)
        asset_type, direction = normalize.parse_asset(
            raw_row.get("asset_name"), raw_row.get("asset_type_hint"))
        lag = (disclosure_date - trade_date).days if disclosure_date else None

        record = {
            "person_id": person_id,
            "official_person_id": member_id if relation != "self" else None,
            "owner_code": raw_row.get("owner_code"),
            "trade_date": trade_date,
            "disclosure_date": disclosure_date,
            "disclosure_lag_days": lag,
            "ticker": normalize.clean_ticker(raw_row.get("ticker")),
            "asset_name": raw_row.get("asset_name"),
            "asset_type": asset_type,
            "direction": direction,
            "side": normalize.parse_side(raw_row.get("transaction_type")),
            "sector": raw_row.get("sector") or None,
            "sector_source": "source" if raw_row.get("sector") else None,
            "option_strike": None,
            "option_expiry": None,
            "filing_id": raw_row.get("filing_id"),
            "source": raw_row.get("source") or source,
            "source_url": raw_row.get("source_url") or source_url,
            "raw": raw_row.get("raw") or json.dumps(
                {k: str(v) for k, v in raw_row.items()}, default=str),
            **amount,
        }
        record["trade_id"] = _trade_id(record)
        trades.append(record)

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        before = len(trades_df)
        trades_df = trades_df.drop_duplicates(subset=["trade_id"])
        if before != len(trades_df):
            notes.append(f"{before - len(trades_df)} duplicate disclosure rows collapsed")
        no_ticker = int(trades_df["ticker"].isna().sum())
        if no_ticker:
            notes.append(
                f"{no_ticker}/{len(trades_df)} disclosure rows carry no usable ticker "
                "(funds, bonds, private assets); they stay in `trades` for the record "
                "but cannot be priced and are excluded from returns")
    if dropped_no_date:
        notes.append(f"{dropped_no_date} rows dropped: unparseable transaction date")
    if unmatched_filers:
        notes.append(
            f"{len(unmatched_filers)} filer names did not match the roster "
            f"(name formatting differs across sources), e.g. "
            f"{sorted(unmatched_filers)[:5]}")

    return pd.DataFrame(list(people.values())), trades_df, notes


def _ensure_person(people: dict, person_id: str, full_name: str, relation: str,
                   official_person_id: str | None, meta: dict | None,
                   chamber_hint, source: str, source_url: str,
                   roster_source: str | None = None) -> str:
    if person_id not in people:
        meta = meta or {}
        people[person_id] = {
            "person_id": person_id,
            "bioguide_id": meta.get("bioguide_id"),
            "full_name": full_name,
            "filer_name": full_name,
            "relation": relation,
            "official_person_id": official_person_id,
            "chamber": meta.get("chamber") or chamber_hint,
            "party": meta.get("party"),
            "state": meta.get("state"),
            "district": meta.get("district"),
            "term_start": normalize.parse_date(meta.get("term_start")),
            "term_end": normalize.parse_date(meta.get("term_end")),
            "source": source if not meta else f"{source}+{roster_source or 'roster'}",
            "roster_source": roster_source if meta else None,
            "source_url": source_url,
            "ingested_at": datetime.now(),
        }
    return person_id


# --------------------------------------------------------------------------
# Analyze
# --------------------------------------------------------------------------

def analyze(con, cfg: Config, run_id: str, as_of: date | None = None) -> dict:
    """Net trades into positions, compute returns, alpha, events and scores."""
    def logger(level, message, stage="analyze"):
        db.log(con, run_id, stage, level, message)

    trades_df = con.execute("SELECT * FROM trades").df()
    if trades_df.empty:
        logger("ERROR", "no trades in database; run ingest first")
        return {"positions": 0}

    prices_df = con.execute("SELECT * FROM prices").df()
    book = PriceBook(prices_df)
    if prices_df.empty:
        logger("ERROR", "no price data: returns, alpha and the event trading-day "
                        "window cannot be computed")
    as_of = as_of or (book.last_date(cfg.market_benchmark) or date.today())
    logger("INFO", f"as-of date for unrealized marks: {as_of}")

    priced = trades_df[trades_df["ticker"].notna()].copy()
    result = netting.net_trades(priced)
    for note in result.notes:
        logger("WARN", note, "analyze:netting")
    positions = result.positions
    if positions.empty:
        logger("ERROR", "netting produced no positions")
        return {"positions": 0}
    logger("INFO", f"netted {len(priced)} priced disclosure lines into "
                   f"{len(positions)} positions "
                   f"({int(positions['is_open'].sum())} still open)")

    events_df = con.execute("SELECT * FROM events").df()
    links = link_trades_to_events(positions, events_df, book,
                                  cfg.event_window_trading_days)
    db.replace_table(con, "trade_event_links", links)
    logger("INFO", f"event links: {len(links)} "
                   f"(window {cfg.event_window_trading_days} trading days, "
                   f"{len(events_df)} events)")

    trade_metrics = metrics.build_trade_metrics(
        positions, book, cfg, nearest_event_by_trade(links), as_of)
    complete = int(trade_metrics["price_data_complete"].sum())
    logger("INFO", f"trade metrics: {len(trade_metrics)} positions, "
                   f"{complete} with complete price coverage "
                   f"({complete / max(len(trade_metrics), 1):.1%})")

    people_df = con.execute("SELECT * FROM people").df()
    person_metrics = metrics.build_person_metrics(trade_metrics, people_df,
                                                  trades_df, cfg)
    person_metrics = scoring.compute_scores(
        person_metrics, cfg.weights, cfg.min_trades_for_ranking)
    eligible = int(person_metrics["eligible_for_ranking"].sum()) if not person_metrics.empty else 0
    logger("INFO", f"person metrics: {len(person_metrics)} people, "
                   f"{eligible} eligible for ranking "
                   f"(min {cfg.min_trades_for_ranking} positions)")

    db.replace_table(con, "positions", positions)
    db.replace_table(con, "trade_metrics", trade_metrics)
    db.replace_table(con, "person_metrics", person_metrics)

    return {
        "positions": len(positions),
        "trade_metrics": len(trade_metrics),
        "person_metrics": len(person_metrics),
        "eligible": eligible,
        "as_of": as_of,
        "netting_notes": result.notes,
        "price_complete_share": complete / max(len(trade_metrics), 1),
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def _price_source_url(source: str | None) -> str:
    """Map a stored price-source label back to a citable location."""
    if not source:
        return "n/a"
    if source.startswith("local_csv:"):
        return source.split(":", 1)[1]
    return {
        "yfinance": "https://finance.yahoo.com/ (via yfinance)",
        "alphavantage": prices_src.ALPHA_VANTAGE_URL,
    }.get(source, source)


def _roster_source_url(source: str | None) -> str:
    """Map a stored roster-source label back to a citable location."""
    if not source:
        return "n/a"
    return {
        "congress-legislators": roster_src.REPO_URL,
    }.get(source, source)


def build_report(con, cfg: Config, run_id: str, out_dir: Path,
                 as_of: date | None = None) -> dict[str, Path]:
    person_metrics = con.execute("SELECT * FROM person_metrics").df()
    trade_metrics = con.execute("SELECT * FROM trade_metrics").df()
    if person_metrics.empty:
        raise RuntimeError("no person_metrics; run analyze first")

    trade_src = con.execute(
        "SELECT source, any_value(source_url), count(*) c FROM trades "
        "GROUP BY source ORDER BY c DESC LIMIT 1").fetchone()
    price_src = con.execute(
        "SELECT source, count(*) c FROM prices GROUP BY source ORDER BY c DESC LIMIT 1"
    ).fetchone()
    event_src = con.execute(
        "SELECT any_value(source), any_value(source_url) FROM events").fetchone()
    roster_src_row = con.execute(
        "SELECT roster_source, count(*) c FROM people "
        "WHERE roster_source IS NOT NULL GROUP BY roster_source "
        "ORDER BY c DESC LIMIT 1").fetchone()

    total_positions = len(trade_metrics)
    complete = int(trade_metrics["price_data_complete"].sum()) if total_positions else 0
    coverage = {
        "Disclosure lines ingested": f"{db.table_count(con, 'trades'):,}",
        "People on record": f"{db.table_count(con, 'people'):,}",
        "Positions after netting": f"{total_positions:,}",
        "Positions with complete price data": f"{complete:,} "
                                              f"({complete / max(total_positions, 1):.1%})",
        "Positions still open (UNREALIZED)": f"{int(trade_metrics['is_open'].sum()):,}"
                                             if total_positions else "0",
        "Curated events": f"{db.table_count(con, 'events'):,}",
        "Trade-event links": f"{db.table_count(con, 'trade_event_links'):,}",
        "People eligible for ranking": f"{int(person_metrics['eligible_for_ranking'].sum()):,}",
    }
    notes = [r[0] for r in con.execute(
        "SELECT DISTINCT message FROM run_log WHERE level IN ('WARN','ERROR') "
        "AND run_id = ? ORDER BY message", [run_id]).fetchall()]

    ctx = report.ReportContext(
        as_of=as_of or date.today(),
        run_id=run_id,
        trade_source=(trade_src[0] if trade_src else "none"),
        trade_source_url=(trade_src[1] if trade_src else "n/a"),
        price_source=(price_src[0] if price_src else "none"),
        price_source_url=_price_source_url(price_src[0] if price_src else None),
        roster_source=(roster_src_row[0] if roster_src_row and roster_src_row[0]
                       else "none (no roster matched)"),
        roster_source_url=_roster_source_url(
            roster_src_row[0] if roster_src_row else None),
        event_source=(event_src[0] if event_src and event_src[0] else "none"),
        event_source_url=(event_src[1] if event_src and event_src[1] else "n/a"),
        weights=cfg.weights,
        min_trades=cfg.min_trades_for_ranking,
        top_trades_per_person=cfg.top_trades_per_person,
        top_trades_selection=cfg.top_trades_selection,
        event_window_trading_days=cfg.event_window_trading_days,
        short_benchmark_mode=cfg.short_benchmark_mode,
        coverage=coverage,
        data_notes=notes,
    )

    out_dir = Path(out_dir)
    paths = report.write_csvs(out_dir, person_metrics, trade_metrics, cfg.report_top_n)
    md_path = out_dir / "ranked_report.md"
    md_path.write_text(report.render_markdown(
        ctx, person_metrics, trade_metrics, cfg.report_top_n))
    paths["markdown"] = md_path
    return paths
