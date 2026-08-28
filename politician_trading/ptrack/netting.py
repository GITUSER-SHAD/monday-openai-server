"""Buy/sell netting.

Requirement 4 of the methodology: multiple disclosure lines in the same ticker
by the same person are netted into positions rather than treated as independent
trades. Matching is FIFO.

The unavoidable approximation: PTRs disclose a dollar RANGE and no share count,
so lots are matched on ESTIMATED DOLLARS (range midpoints), not shares. A sale
therefore closes "the first N estimated dollars" of prior purchases. Returns are
computed from prices, so this approximation affects only how much weight a lot
carries, never the return itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Which side opens a position depends on the instrument, not on the direction:
#   equity / etf / call / put : a purchase opens, a sale closes
#   explicit short sale       : the sale opens, the covering purchase closes
_SHORT_SALE_TYPES = {"short"}


def asset_group(asset_type: str | None) -> str:
    """Netting bucket. A call purchase must not be netted against a stock sale."""
    at = (asset_type or "unknown").lower()
    if at in {"equity", "etf", "stock", "unknown"}:
        return "equity"
    if at in {"option_call", "option_put", "short"}:
        return at
    return "other"


def opens_position(asset_type: str | None, side: str | None) -> bool:
    side = (side or "").lower()
    if asset_group(asset_type) in _SHORT_SALE_TYPES:
        return side == "sell"
    return side == "buy"


def closes_position(asset_type: str | None, side: str | None) -> bool:
    side = (side or "").lower()
    if asset_group(asset_type) in _SHORT_SALE_TYPES:
        return side == "buy"
    return side == "sell"


@dataclass
class _Lot:
    trade_id: str
    open_date: object
    remaining: float
    original: float          # lot size before any partial exits consumed it
    amount_range: str | None
    direction: str
    asset_type: str
    sector: str | None
    disclosure_date: object
    disclosure_lag_days: object


@dataclass
class NettingReport:
    positions: pd.DataFrame
    orphan_closes: int = 0            # sale with no matching prior purchase on record
    unparsed_side: int = 0            # transaction type we could not classify
    zero_amount_lots: int = 0         # amount range unparseable -> weight unknown
    notes: list[str] = field(default_factory=list)


# A sale with no prior purchase in the data is expected, not a bug: disclosure
# history begins mid-stream, so pre-existing holdings are sold "out of nowhere".
# Such rows cannot yield a return (no entry price) and are excluded from metrics.
def net_trades(trades: pd.DataFrame) -> NettingReport:
    """FIFO-net disclosure lines into positions.

    Input: the `trades` table. Output: one row per matched or still-open lot.
    """
    if trades.empty:
        return NettingReport(positions=pd.DataFrame())

    df = trades.copy()
    df["_group"] = df["asset_type"].map(asset_group)
    df = df.sort_values(["person_id", "ticker", "_group", "trade_date", "trade_id"],
                        kind="mergesort")

    rows: list[dict] = []
    orphan_closes = unparsed_side = zero_amount_lots = 0

    for (person_id, ticker, group), chunk in df.groupby(
        ["person_id", "ticker", "_group"], dropna=False, sort=False
    ):
        open_lots: list[_Lot] = []
        for trade in chunk.to_dict("records"):
            side = trade.get("side")
            amount = trade.get("amount_mid")
            amount = 0.0 if amount is None or pd.isna(amount) else float(amount)
            if amount <= 0:
                zero_amount_lots += 1

            if opens_position(trade.get("asset_type"), side):
                open_lots.append(_Lot(
                    trade_id=trade["trade_id"],
                    open_date=trade.get("trade_date"),
                    remaining=amount,
                    original=amount,
                    amount_range=trade.get("amount_range_text"),
                    direction=trade.get("direction") or "long",
                    asset_type=trade.get("asset_type") or "unknown",
                    sector=trade.get("sector"),
                    disclosure_date=trade.get("disclosure_date"),
                    disclosure_lag_days=trade.get("disclosure_lag_days"),
                ))
            elif closes_position(trade.get("asset_type"), side):
                to_close = amount
                if not open_lots:
                    orphan_closes += 1
                    continue
                # A close with an unparseable amount still closes the oldest lot
                # entirely: the alternative is silently dropping a real exit.
                if to_close <= 0:
                    to_close = open_lots[0].remaining

                while to_close > 0 and open_lots:
                    lot = open_lots[0]
                    matched = min(lot.remaining, to_close) if lot.remaining > 0 else to_close
                    rows.append(_position_row(
                        person_id, ticker, group, lot, trade, matched, is_open=False))
                    lot.remaining -= matched
                    to_close -= matched
                    if lot.remaining <= 1e-9:
                        open_lots.pop(0)
                if to_close > 1e-9:
                    orphan_closes += 1
            else:
                unparsed_side += 1

        for lot in open_lots:                      # still held -> unrealized
            rows.append(_position_row(
                person_id, ticker, group, lot, None, lot.remaining, is_open=True))

    positions = pd.DataFrame(rows)
    notes = []
    if orphan_closes:
        notes.append(
            f"{orphan_closes} sales had no matching prior purchase on record "
            "(holdings pre-dating the disclosure history); excluded from returns")
    if unparsed_side:
        notes.append(f"{unparsed_side} rows had an unclassifiable transaction type")
    if zero_amount_lots:
        notes.append(f"{zero_amount_lots} rows had an unparseable amount range")

    return NettingReport(positions=positions, orphan_closes=orphan_closes,
                         unparsed_side=unparsed_side,
                         zero_amount_lots=zero_amount_lots, notes=notes)


def _position_row(person_id, ticker, group, lot: _Lot, close_trade: dict | None,
                  matched: float, is_open: bool) -> dict:
    close_id = None if close_trade is None else close_trade["trade_id"]
    suffix = "open" if is_open else close_id
    return {
        "position_id": f"{lot.trade_id}::{suffix}",
        "person_id": person_id,
        "ticker": ticker,
        "sector": lot.sector,
        "direction": lot.direction,
        "asset_type": lot.asset_type,
        "asset_group": group,
        "open_trade_id": lot.trade_id,
        "close_trade_id": close_id,
        "open_date": lot.open_date,
        "close_date": None if close_trade is None else close_trade.get("trade_date"),
        "is_open": is_open,
        "matched_amount_mid": matched,
        "open_amount_mid": lot.original,
        # A sale can close only part of a lot. The matched slice is what carries
        # weight in aggregates; the full lot is kept so the report never prints a
        # slice next to the whole disclosed range as if they were the same thing.
        "is_partial_lot": bool(lot.original > 0 and matched < lot.original - 1e-9),
        "open_amount_range": lot.amount_range,
        "close_amount_range": None if close_trade is None else close_trade.get("amount_range_text"),
        "amount_is_estimate": True,
        "disclosure_date": lot.disclosure_date,
        "disclosure_lag_days": lot.disclosure_lag_days,
    }
