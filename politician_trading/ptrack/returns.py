"""Return and benchmark math.

Two metrics are computed and kept strictly separate, per the methodology:

  disclosure_drift_pct  price move between the trade date and the date the trade
                        was disclosed. This measures REPORTING LAG, not skill.
                        It is reported on its own and never enters a ranking.

  position_return_pct   price move over the actual holding window: entry to the
                        matching exit, or entry to the as-of date for a position
                        still held (then flagged UNREALIZED).

Every return is benchmarked over the IDENTICAL window against SPY and against
the sector ETF, and it is the excess return (alpha) that is ranked.

Price convention (applies to every lookup, so entries, exits and benchmarks are
treated identically):
  * all math uses adj_close (split- and dividend-adjusted)
  * an entry/exit dated on a non-trading day uses the FIRST trading day on or
    after that date — the earliest price actually observable for that order
  * a position still open is marked at the LAST trading day on or before the
    as-of date
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

LONG_BENCHMARK = "long_benchmark"
SIGN_MATCHED = "sign_matched"


class PriceBook:
    """Indexed adjusted-close series with trading-calendar lookups."""

    def __init__(self, prices: pd.DataFrame):
        self._series: dict[str, pd.Series] = {}
        if prices is None or prices.empty:
            self._calendar = pd.DatetimeIndex([])
            return
        df = prices.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna(subset=["adj_close"]).sort_values("date")
        for ticker, chunk in df.groupby("ticker"):
            self._series[str(ticker)] = pd.Series(
                chunk["adj_close"].to_numpy(dtype=float),
                index=pd.DatetimeIndex(chunk["date"]),
            ).groupby(level=0).last()
        self._calendar = self._build_calendar()

    def _build_calendar(self) -> pd.DatetimeIndex:
        """Trading calendar taken from the market benchmark where available.

        Using an observed price series avoids depending on an exchange-holiday
        package, and guarantees the calendar matches the data we actually hold.
        """
        for proxy in ("SPY", "^GSPC"):
            if proxy in self._series:
                return self._series[proxy].index
        if not self._series:
            return pd.DatetimeIndex([])
        union = pd.DatetimeIndex([])
        for series in self._series.values():
            union = union.union(series.index)
        return union.sort_values()

    @property
    def calendar(self) -> pd.DatetimeIndex:
        return self._calendar

    def has(self, ticker: str | None) -> bool:
        return bool(ticker) and ticker in self._series

    def price_on_or_after(self, ticker: str | None, when) -> float | None:
        series = self._series.get(str(ticker)) if ticker else None
        if series is None or when is None:
            return None
        ts = pd.Timestamp(when)
        idx = series.index.searchsorted(ts, side="left")
        if idx >= len(series):
            return None
        return float(series.iloc[idx])

    def price_on_or_before(self, ticker: str | None, when) -> float | None:
        series = self._series.get(str(ticker)) if ticker else None
        if series is None or when is None:
            return None
        ts = pd.Timestamp(when)
        idx = series.index.searchsorted(ts, side="right") - 1
        if idx < 0:
            return None
        return float(series.iloc[idx])

    def last_date(self, ticker: str | None):
        series = self._series.get(str(ticker)) if ticker else None
        if series is None or series.empty:
            return None
        return series.index[-1].date()

    def trading_days_between(self, start, end) -> int | None:
        """Trading days from `start` to `end` (negative if end precedes start)."""
        if start is None or end is None or len(self._calendar) == 0:
            return None
        s, e = pd.Timestamp(start), pd.Timestamp(end)
        sign = 1 if e >= s else -1
        lo, hi = (s, e) if sign == 1 else (e, s)
        count = int(((self._calendar >= lo) & (self._calendar < hi)).sum())
        return sign * count


@dataclass
class WindowReturn:
    value: float | None
    entry_price: float | None
    exit_price: float | None
    complete: bool


def window_return(book: PriceBook, ticker: str | None, start, end,
                  mark_to_last: bool = False) -> WindowReturn:
    """Raw (un-directioned) price return over [start, end]."""
    entry = book.price_on_or_after(ticker, start)
    exit_ = (book.price_on_or_before(ticker, end) if mark_to_last
             else book.price_on_or_after(ticker, end))
    if entry is None or exit_ is None or entry == 0:
        return WindowReturn(None, entry, exit_, False)
    return WindowReturn(exit_ / entry - 1.0, entry, exit_, True)


def direction_sign(direction: str | None) -> int:
    return -1 if (direction or "long").lower() == "short" else 1


def position_return(book: PriceBook, ticker: str | None, direction: str | None,
                    start, end, mark_to_last: bool = False) -> WindowReturn:
    """Direction-adjusted return: a short profits when the underlying falls."""
    raw = window_return(book, ticker, start, end, mark_to_last=mark_to_last)
    if raw.value is None:
        return raw
    return WindowReturn(direction_sign(direction) * raw.value,
                        raw.entry_price, raw.exit_price, raw.complete)


def alpha(position_ret: float | None, benchmark_ret: float | None,
          direction: str | None, mode: str = LONG_BENCHMARK) -> float | None:
    """Excess return over a benchmark held across the identical window.

    long_benchmark (default): alpha = position_return - benchmark_return, i.e.
      "versus simply holding the index over the same days". For a short or put
      this compares a short position against a long benchmark, which is
      asymmetric by construction — documented, not hidden.

    sign_matched: the benchmark is given the position's own sign, so a short is
      compared against shorting the index. Selectable via config.
    """
    if position_ret is None or benchmark_ret is None:
        return None
    if mode == SIGN_MATCHED:
        benchmark_ret = direction_sign(direction) * benchmark_ret
    return position_ret - benchmark_ret


def disclosure_drift(book: PriceBook, ticker: str | None, direction: str | None,
                     trade_date, disclosure_date) -> float | None:
    """Price move between trading and disclosing, in the filer's direction.

    Reported separately. It quantifies how stale a filing was by the time the
    public could see it; it says nothing about the quality of the decision.
    """
    if trade_date is None or disclosure_date is None:
        return None
    ret = position_return(book, ticker, direction, trade_date, disclosure_date)
    return ret.value


def safe_stat(values, fn) -> float | None:
    arr = pd.Series([v for v in values if v is not None and not pd.isna(v)], dtype=float)
    if arr.empty:
        return None
    result = fn(arr)
    return None if pd.isna(result) else float(result)


def mean_of(values) -> float | None:
    return safe_stat(values, np.mean)


def median_of(values) -> float | None:
    return safe_stat(values, np.median)
