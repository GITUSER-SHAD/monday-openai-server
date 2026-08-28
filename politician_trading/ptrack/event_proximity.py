"""Event-proximity flagging.

Methodology rule 5: flag trades OPENED within N trading days BEFORE an event
whose category matches the trade's sector, and report the result as a FREQUENCY
STATISTIC.

What this measures and what it does not
---------------------------------------
A proximity flag says only: this position was opened shortly before a dated
public event touching the same sector. Base rates matter enormously — a member
who trades energy names weekly will sit near energy events by arithmetic alone,
and the curated event list is itself a human selection. The flag is a pointer to
things worth reading, never an inference about knowledge, motive, or legality.
"""

from __future__ import annotations

import pandas as pd

from .returns import PriceBook


def parse_event_sectors(cell) -> set[str]:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return set()
    return {s.strip() for s in str(cell).split("|") if s.strip()}


def link_trades_to_events(positions: pd.DataFrame, events: pd.DataFrame,
                          book: PriceBook, window_trading_days: int = 10
                          ) -> pd.DataFrame:
    """Return trade_event_links rows: opened <= N trading days before an event.

    Only the OPENING date of a position is tested. A position is linked to every
    qualifying event; the nearest one is surfaced in the per-trade report.
    """
    empty = pd.DataFrame(columns=[
        "trade_id", "event_id", "matched_sector",
        "trading_days_before", "calendar_days_before",
    ])
    if positions is None or positions.empty or events is None or events.empty:
        return empty

    events = events.copy()
    events["parsed_sectors"] = events["sectors"].map(parse_event_sectors)
    events["parsed_date"] = pd.to_datetime(events["event_date"])

    by_sector: dict[str, list[tuple]] = {}
    for row in events.itertuples(index=False):
        for sector in row.parsed_sectors:
            by_sector.setdefault(sector, []).append((row.event_id, row.parsed_date))

    links: list[dict] = []
    for pos in positions.itertuples(index=False):
        sector = getattr(pos, "sector", None)
        open_date = getattr(pos, "open_date", None)
        if not sector or open_date is None or sector not in by_sector:
            continue
        open_ts = pd.Timestamp(open_date)
        for event_id, event_ts in by_sector[sector]:
            if event_ts < open_ts:
                continue
            trading_days = book.trading_days_between(open_ts, event_ts)
            if trading_days is None or trading_days > window_trading_days:
                continue
            links.append({
                "trade_id": getattr(pos, "open_trade_id"),
                "event_id": event_id,
                "matched_sector": sector,
                "trading_days_before": int(trading_days),
                "calendar_days_before": int((event_ts - open_ts).days),
            })

    if not links:
        return empty
    return (pd.DataFrame(links)
            .sort_values(["trade_id", "trading_days_before"])
            .drop_duplicates(subset=["trade_id", "event_id"], keep="first"))


def nearest_event_by_trade(links: pd.DataFrame) -> dict[str, tuple[str, int]]:
    """trade_id -> (event_id, trading_days_before) for the closest event."""
    if links is None or links.empty:
        return {}
    best = links.sort_values("trading_days_before").drop_duplicates("trade_id", keep="first")
    return {r.trade_id: (r.event_id, int(r.trading_days_before))
            for r in best.itertuples(index=False)}
