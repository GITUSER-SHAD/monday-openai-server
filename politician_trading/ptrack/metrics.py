"""Per-trade and per-person metric assembly."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import Config
from .returns import (LONG_BENCHMARK, PriceBook, alpha, disclosure_drift,
                      mean_of, median_of, position_return, window_return)

OPTION_TYPES = {"option_call", "option_put"}


def build_trade_metrics(positions: pd.DataFrame, book: PriceBook, cfg: Config,
                        nearest_events: dict[str, tuple[str, int]],
                        as_of: date) -> pd.DataFrame:
    """One row per netted position, with returns, benchmarks and alpha."""
    if positions is None or positions.empty:
        return pd.DataFrame()

    market = cfg.market_benchmark
    rows: list[dict] = []

    for pos in positions.to_dict("records"):
        ticker = pos.get("ticker")
        direction = pos.get("direction") or "long"
        asset_type = pos.get("asset_type") or "unknown"
        is_open = bool(pos.get("is_open"))
        open_date = pos.get("open_date")
        close_date = pos.get("close_date") if not is_open else as_of

        # An option's payoff needs a strike and an expiry, which a PTR does not
        # disclose. We therefore report the DIRECTION-ADJUSTED UNDERLYING move
        # and label it as a proxy. It is not the option's profit or loss.
        return_basis = ("underlying_proxy_for_option" if asset_type in OPTION_TYPES
                        else "underlying_adjusted_close")

        pos_ret = position_return(book, ticker, direction, open_date, close_date,
                                  mark_to_last=is_open)
        spy_raw = window_return(book, market, open_date, close_date, mark_to_last=is_open)
        sector_etf, is_fallback = cfg.sector_etf_for(pos.get("sector"))
        sec_raw = window_return(book, sector_etf, open_date, close_date, mark_to_last=is_open)

        drift = disclosure_drift(book, ticker, direction, open_date,
                                 pos.get("disclosure_date"))

        event_id, days_before = nearest_events.get(pos.get("open_trade_id"), (None, None))
        holding_days = (None if open_date is None or close_date is None
                        else (pd.Timestamp(close_date) - pd.Timestamp(open_date)).days)

        rows.append({
            "position_id": pos["position_id"],
            "person_id": pos["person_id"],
            "ticker": ticker,
            "sector": pos.get("sector"),
            "direction": direction,
            "asset_type": asset_type,
            "open_date": open_date,
            "close_date": None if is_open else pos.get("close_date"),
            "disclosure_date": pos.get("disclosure_date"),
            "disclosure_lag_days": pos.get("disclosure_lag_days"),
            "holding_days": holding_days,
            "is_open": is_open,
            "return_basis": return_basis,
            "disclosure_drift_pct": drift,
            "position_return_pct": pos_ret.value,
            "spy_return_pct": spy_raw.value,
            "sector_etf": sector_etf,
            "sector_etf_return_pct": sec_raw.value,
            "alpha_vs_spy": alpha(pos_ret.value, spy_raw.value, direction,
                                  cfg.short_benchmark_mode),
            "alpha_vs_sector_etf": alpha(pos_ret.value, sec_raw.value, direction,
                                         cfg.short_benchmark_mode),
            "sector_benchmark_is_fallback": is_fallback,
            "est_amount_mid": pos.get("matched_amount_mid"),
            "est_open_amount_mid": pos.get("open_amount_mid"),
            "is_partial_lot": bool(pos.get("is_partial_lot")),
            "amount_range_text": pos.get("open_amount_range"),
            "matched_event_id": event_id,
            "matched_event_days_before": days_before,
            "price_data_complete": bool(
                pos_ret.complete and spy_raw.complete and sec_raw.complete),
        })

    return pd.DataFrame(rows)


def select_top_trades(person_trades: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Apply the 'top N trades per person' rule from config."""
    n = cfg.top_trades_per_person
    if len(person_trades) <= n:
        return person_trades
    if cfg.top_trades_selection == "most_recent":
        return person_trades.sort_values("open_date", ascending=False).head(n)
    return person_trades.sort_values("est_amount_mid", ascending=False).head(n)


def build_person_metrics(trade_metrics: pd.DataFrame, people: pd.DataFrame,
                         trades: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Aggregate per person over their top-N trades.

    Only positions with complete price data enter the performance statistics;
    the count of positions dropped for missing prices is reported separately so
    coverage is never silently hidden inside an average.
    """
    if trade_metrics is None or trade_metrics.empty:
        return pd.DataFrame()

    usable = trade_metrics[trade_metrics["price_data_complete"]].copy()
    disclosed_counts = (trades.groupby("person_id").size().to_dict()
                        if trades is not None and not trades.empty else {})
    people_ix = (people.set_index("person_id") if people is not None and not people.empty
                 else pd.DataFrame())

    rows: list[dict] = []
    for person_id, chunk in usable.groupby("person_id"):
        top = select_top_trades(chunk, cfg)
        returns = top["position_return_pct"].dropna()
        closed = top[~top["is_open"]]

        est_total = float(top["est_amount_mid"].fillna(0).sum())
        sector_notional = top.groupby(top["sector"].fillna("unclassified"))[
            "est_amount_mid"].sum().sort_values(ascending=False)
        top_sector = sector_notional.index[0] if len(sector_notional) else None
        concentration = (float(sector_notional.iloc[0] / est_total * 100.0)
                         if est_total > 0 and len(sector_notional) else None)

        meta = (people_ix.loc[person_id].to_dict()
                if len(people_ix) and person_id in people_ix.index else {})

        rows.append({
            "person_id": person_id,
            "full_name": meta.get("full_name", person_id),
            "relation": meta.get("relation"),
            "official_person_id": meta.get("official_person_id"),
            "chamber": meta.get("chamber"),
            "party": meta.get("party"),
            "state": meta.get("state"),
            "trades_disclosed": int(disclosed_counts.get(person_id, 0)),
            "positions_analyzed": int(len(top)),
            "positions_closed": int(len(closed)),
            "positions_open": int(len(top) - len(closed)),
            "win_rate": float((returns > 0).mean()) if len(returns) else None,
            "win_rate_closed": (float((closed["position_return_pct"] > 0).mean())
                                if len(closed) else None),
            "mean_return_pct": mean_of(top["position_return_pct"]),
            "median_return_pct": median_of(top["position_return_pct"]),
            "mean_alpha_vs_spy": mean_of(top["alpha_vs_spy"]),
            "median_alpha_vs_spy": median_of(top["alpha_vs_spy"]),
            "mean_alpha_vs_sector_etf": mean_of(top["alpha_vs_sector_etf"]),
            "median_alpha_vs_sector_etf": median_of(top["alpha_vs_sector_etf"]),
            "median_disclosure_drift_pct": median_of(top["disclosure_drift_pct"]),
            "median_disclosure_lag_days": median_of(top["disclosure_lag_days"]),
            "top_sector": top_sector,
            "sector_concentration_pct": concentration,
            "event_proximity_rate": float(top["matched_event_id"].notna().mean()),
            "est_total_notional": est_total,
            "positions_dropped_no_prices": int(
                (trade_metrics["person_id"] == person_id).sum() - len(chunk)),
        })

    return pd.DataFrame(rows)


def sector_concentration_note() -> str:
    return ("sector_concentration_pct is share of ESTIMATED notional (range "
            "midpoints) in the person's largest sector, not an exact figure")
