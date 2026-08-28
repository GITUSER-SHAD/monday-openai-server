"""Ranked report generation (Markdown + CSV).

Presentation rules enforced here, not left to the reader:
  * every dollar figure is printed with a ~ and the disclosed range beside it
  * unrealized returns are labelled UNREALIZED at the point of use
  * option returns are labelled as underlying proxies at the point of use
  * disclosure drift is printed in its own column, never mixed into performance
  * each figure names the source it came from
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .scoring import COMPONENTS, formula_text


@dataclass
class ReportContext:
    as_of: date
    run_id: str
    trade_source: str
    trade_source_url: str
    price_source: str
    price_source_url: str
    roster_source: str
    roster_source_url: str
    event_source: str
    event_source_url: str
    weights: dict[str, float]
    min_trades: int
    top_trades_per_person: int
    top_trades_selection: str
    event_window_trading_days: int
    short_benchmark_mode: str
    coverage: dict = field(default_factory=dict)
    data_notes: list[str] = field(default_factory=list)


def _pct(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:+.{digits}f}%"


def _rate(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def _money_est(value) -> str:
    """Never print an estimated dollar figure without marking it as one."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"~${float(value):,.0f} (est.)"


def _date(value) -> str:
    """Dates round-trip through DuckDB as timestamps; print them as dates."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "n/a"
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(value)


def _num(value, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def write_csvs(out_dir: Path, person_metrics: pd.DataFrame,
               trade_metrics: pd.DataFrame, top_n: int) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    ranked = person_metrics[person_metrics["eligible_for_ranking"]].head(top_n)
    paths["ranked"] = out_dir / "ranked_people.csv"
    ranked.to_csv(paths["ranked"], index=False)

    paths["person_metrics"] = out_dir / "person_metrics.csv"
    person_metrics.to_csv(paths["person_metrics"], index=False)

    paths["trade_metrics"] = out_dir / "trade_metrics.csv"
    trade_metrics.to_csv(paths["trade_metrics"], index=False)
    return paths


def render_markdown(ctx: ReportContext, person_metrics: pd.DataFrame,
                    trade_metrics: pd.DataFrame, top_n: int) -> str:
    lines: list[str] = []
    add = lines.append

    add("# Public-Disclosure Trading Analysis — Ranked Report")
    add("")
    add(f"**Run:** `{ctx.run_id}`  ")
    add(f"**Prices as of:** {ctx.as_of}  ")
    add(f"**People ranked:** top {top_n} by composite score "
        f"(minimum {ctx.min_trades} analysed positions to be eligible)")
    add("")

    add("## How to read this report")
    add("")
    add("- Every dollar figure is an **estimate**. Disclosures report amount "
        "*ranges*, never exact amounts; midpoints are used throughout and the "
        "range is carried beside the estimate.")
    add("- A sale can close only part of an earlier purchase. Where it does, the "
        "row shows the **matched slice**, which is smaller than the opening "
        "disclosure's range, and says so explicitly.")
    add("- Returns marked **UNREALIZED** are positions still held, marked to the "
        "as-of price. They are not booked gains.")
    add("- Returns for options are the **direction-adjusted move in the "
        "underlying**, not the option's profit and loss: a periodic transaction "
        "report discloses no strike and no expiry, so true option P&L is not "
        "derivable from public data.")
    add("- **Disclosure-window drift** is reported in its own column. It measures "
        "reporting lag only and is excluded from every ranking.")
    add("- **Event-proximity** flags are frequency statistics. They indicate that "
        "a position was opened shortly before a dated public event in the same "
        "sector. They are correlational, are sensitive to how often a person "
        "trades that sector at all, and are **not** evidence of knowledge, "
        "intent, or wrongdoing.")
    add("- Nothing here asserts illegality. These are public filings analysed "
        "statistically.")
    add("")

    add("## Composite score formula")
    add("")
    add("```")
    add(f"score = {formula_text(ctx.weights)}")
    add("```")
    add("")
    add("Raw components are shown for every person so the score can be "
        "recomputed by hand. Two caveats travel with it:")
    add("")
    add("1. **Mixed units.** Alpha terms are return fractions (`0.08` = +8pp); "
        "win rate and event-proximity rate are bounded rates in `[0,1]`. Summing "
        "them makes one point of win rate worth a hundred points of alpha. The "
        "`composite_score_normalized` column re-weights each component by its "
        "percentile within the eligible cohort and is the fairer comparison.")
    add("2. **Event proximity is a positive term** in this formula, so trading "
        "near events raises the score. That is a specified weighting, not a "
        "finding about behaviour.")
    add("")

    add("## Data sources")
    add("")
    add("| Data | Source | Location |")
    add("|---|---|---|")
    add(f"| Trades / disclosures | {ctx.trade_source} | {ctx.trade_source_url} |")
    add(f"| Daily prices (adj. close) | {ctx.price_source} | {ctx.price_source_url} |")
    add(f"| Officials roster | {ctx.roster_source} | {ctx.roster_source_url} |")
    add(f"| Event timeline | {ctx.event_source} | {ctx.event_source_url} |")
    add("")

    add("## Methodology settings")
    add("")
    add(f"- Per-person metrics computed over each person's top "
        f"{ctx.top_trades_per_person} trades, selected by `{ctx.top_trades_selection}`.")
    add(f"- Event proximity window: **{ctx.event_window_trading_days} trading days** "
        "before a sector-matched event.")
    add(f"- Short/put benchmark convention: `{ctx.short_benchmark_mode}`.")
    add("- Buy/sell pairs in the same ticker by the same person are netted FIFO "
        "into positions; each disclosure line is *not* treated independently.")
    add("- Benchmarks (SPY and the sector ETF) are measured over the identical "
        "window as the position they are compared against.")
    add("")

    if ctx.coverage:
        add("## Coverage and data quality")
        add("")
        add("| Measure | Value |")
        add("|---|---|")
        for key, value in ctx.coverage.items():
            add(f"| {key} | {value} |")
        add("")
    if ctx.data_notes:
        add("### Data-quality notes")
        add("")
        for note in ctx.data_notes:
            add(f"- {note}")
        add("")

    ranked = person_metrics[person_metrics["eligible_for_ranking"]].head(top_n)
    add(f"## Ranked table — top {len(ranked)}")
    add("")
    if ranked.empty:
        add("_No person met the eligibility threshold._")
        add("")
    else:
        add("| # | Person | Chamber | Positions | Win rate | Mean alpha vs SPY | "
            "Median alpha vs sector | Event prox. | Median lag (d) | Score | Score (norm.) |")
        add("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for i, row in enumerate(ranked.itertuples(index=False), start=1):
            add(f"| {i} | {row.full_name} | {row.chamber or 'n/a'} | "
                f"{row.positions_analyzed} | {_rate(row.win_rate)} | "
                f"{_pct(row.mean_alpha_vs_spy)} | {_pct(row.median_alpha_vs_sector_etf)} | "
                f"{_rate(row.event_proximity_rate)} | "
                f"{_num(row.median_disclosure_lag_days, 0)} | "
                f"{_num(row.composite_score)} | {_num(row.composite_score_normalized)} |")
        add("")

    add("## Person profiles")
    add("")
    if ranked.empty:
        add("_No profiles: no person met the eligibility threshold._")
    for i, row in enumerate(ranked.itertuples(index=False), start=1):
        lines.extend(_profile(i, row, trade_metrics, ctx))

    add("")
    add("---")
    add("")
    add("_All figures derive from mandatory public disclosures and public price "
        "series. Dollar amounts are estimates from disclosed ranges. Performance "
        "and timing patterns are correlational and are not claims about conduct._")
    return "\n".join(lines)


def _profile(index: int, row, trade_metrics: pd.DataFrame,
             ctx: ReportContext) -> list[str]:
    out: list[str] = []
    add = out.append

    add(f"### {index}. {row.full_name}")
    add("")
    meta = " · ".join(str(x) for x in (row.chamber, row.party, row.state) if x and not pd.isna(x))
    if meta:
        add(f"*{meta}*  ")
    if getattr(row, "relation", None) and row.relation != "self":
        add(f"*Filed under a member disclosure as: **{row.relation}***  ")
    add("")

    add("| Metric | Value | Basis |")
    add("|---|---|---|")
    add(f"| Disclosure lines on record | {row.trades_disclosed} | disclosure source |")
    add(f"| Positions analysed (after netting) | {row.positions_analyzed} | "
        f"top {ctx.top_trades_per_person} by {ctx.top_trades_selection} |")
    add(f"| — closed / still held | {row.positions_closed} / {row.positions_open} | "
        "held positions are marked to the as-of price (UNREALIZED) |")
    add(f"| Win rate | {_rate(row.win_rate)} | share of analysed positions with a positive return |")
    add(f"| Mean return | {_pct(row.mean_return_pct)} | direction-adjusted |")
    add(f"| Median return | {_pct(row.median_return_pct)} | direction-adjusted |")
    add(f"| Mean alpha vs SPY | {_pct(row.mean_alpha_vs_spy)} | identical window |")
    add(f"| Median alpha vs SPY | {_pct(row.median_alpha_vs_spy)} | identical window |")
    add(f"| Mean alpha vs sector ETF | {_pct(row.mean_alpha_vs_sector_etf)} | identical window |")
    add(f"| Median alpha vs sector ETF | {_pct(row.median_alpha_vs_sector_etf)} | identical window |")
    add(f"| Median disclosure lag | {_num(row.median_disclosure_lag_days, 0)} days | "
        "trade date to disclosure date |")
    add(f"| Median disclosure-window drift | {_pct(getattr(row, 'median_disclosure_drift_pct', None))} | "
        "**lag metric only — not performance** |")
    add(f"| Sector concentration | {_num(row.sector_concentration_pct, 1)}% in "
        f"`{row.top_sector}` | share of ESTIMATED notional |")
    add(f"| Event-proximity rate | {_rate(row.event_proximity_rate)} | "
        f"positions opened ≤{ctx.event_window_trading_days} trading days before a "
        "sector-matched event — **frequency statistic only** |")
    add(f"| Estimated total notional | {_money_est(row.est_total_notional)} | "
        "sum of disclosed-range midpoints |")
    add(f"| Composite score | {_num(row.composite_score)} "
        f"(normalised {_num(row.composite_score_normalized)}) | formula above |")
    add("")

    best = _best_trades(trade_metrics, row.person_id, n=3)
    if not best.empty:
        add("**Largest-alpha positions**")
        add("")
        add("| Ticker | Sector | Direction | Opened | Closed | Est. amount (range) | "
            "Return | Alpha vs SPY | Alpha vs sector | Event flag |")
        add("|---|---|---|---|---|---|---:|---:|---:|---|")
        for trade in best.itertuples(index=False):
            closed = "still held (UNREALIZED)" if trade.is_open else _date(trade.close_date)
            ret = _pct(trade.position_return_pct)
            if trade.return_basis == "underlying_proxy_for_option":
                ret += " *(underlying proxy)*"
            event = "—"
            if trade.matched_event_id and not pd.isna(trade.matched_event_id):
                event = f"`{trade.matched_event_id}` ({int(trade.matched_event_days_before)}d before)"
            amount = f"{_money_est(trade.est_amount_mid)}"
            if trade.amount_range_text and not pd.isna(trade.amount_range_text):
                amount += f"<br/>opening disclosure: {trade.amount_range_text}"
            if getattr(trade, "is_partial_lot", False):
                amount += (f"<br/>_partial exit: this slice of a "
                           f"{_money_est(trade.est_open_amount_mid)} position_")
            add(f"| {trade.ticker} | {trade.sector or 'n/a'} | {trade.direction} | "
                f"{_date(trade.open_date)} | {closed} | {amount} | {ret} | "
                f"{_pct(trade.alpha_vs_spy)} | {_pct(trade.alpha_vs_sector_etf)} | {event} |")
        add("")
    return out


def _best_trades(trade_metrics: pd.DataFrame, person_id: str, n: int = 3) -> pd.DataFrame:
    if trade_metrics is None or trade_metrics.empty:
        return pd.DataFrame()
    chunk = trade_metrics[(trade_metrics["person_id"] == person_id)
                          & trade_metrics["price_data_complete"]]
    if chunk.empty:
        return chunk
    return chunk.sort_values("alpha_vs_spy", ascending=False).head(n)
