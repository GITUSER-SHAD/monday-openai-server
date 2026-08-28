"""Daily OHLC price sources: yfinance -> Alpha Vantage.

Both adapters return split- and dividend-ADJUSTED closes in `adj_close`. All
return math in the pipeline uses adj_close exclusively, so a split inside a
holding window cannot masquerade as a -50% return.
"""

from __future__ import annotations

import os
import time
from datetime import date

import pandas as pd

from .base import FetchResult, SourceUnavailable, http_get

ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"


def yfinance_prices(tickers: list[str], start: date, end: date,
                    chunk_size: int = 40) -> FetchResult:
    """Primary price source."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SourceUnavailable("yfinance is not installed") from exc

    tickers = sorted({t for t in tickers if t})
    if not tickers:
        raise SourceUnavailable("no tickers requested")

    frames: list[pd.DataFrame] = []
    failures: list[str] = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            raw = yf.download(
                chunk, start=start, end=end, auto_adjust=False,
                actions=False, progress=False, group_by="ticker", threads=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{','.join(chunk)}: {type(exc).__name__}: {exc}")
            continue
        if raw is None or raw.empty:
            failures.append(f"{','.join(chunk)}: empty response")
            continue
        frames.append(_tidy_yf(raw, chunk))

    if not frames:
        raise SourceUnavailable("yfinance returned nothing; " + "; ".join(failures[:3]))

    out = pd.concat(frames, ignore_index=True)
    out["source"] = "yfinance"
    return FetchResult(
        data=out, source="yfinance",
        source_url="https://finance.yahoo.com/",
        notes=failures,
    )


def _tidy_yf(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """Flatten yfinance's wide/multi-index frame into tidy long rows."""
    rows: list[pd.DataFrame] = []
    if isinstance(raw.columns, pd.MultiIndex):
        present = [t for t in tickers if t in raw.columns.get_level_values(0)]
        for ticker in present:
            sub = raw[ticker].copy()
            sub["ticker"] = ticker
            rows.append(sub)
    else:
        sub = raw.copy()
        sub["ticker"] = tickers[0]
        rows.append(sub)

    tidy = pd.concat(rows).reset_index()
    tidy = tidy.rename(columns={
        "Date": "date", "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    if "adj_close" not in tidy.columns:
        tidy["adj_close"] = tidy.get("close")
    keep = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    tidy = tidy[[c for c in keep if c in tidy.columns]].dropna(subset=["date"])
    tidy["date"] = pd.to_datetime(tidy["date"]).dt.date
    return tidy.dropna(subset=["adj_close"])


def alpha_vantage_prices(tickers: list[str], start: date, end: date,
                         sleep_seconds: float = 12.0) -> FetchResult:
    """Fallback price source. Free tier is ~5 requests/min, hence the sleep."""
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key:
        raise SourceUnavailable("ALPHAVANTAGE_API_KEY is not set")

    tickers = sorted({t for t in tickers if t})
    frames, failures = [], []
    for idx, ticker in enumerate(tickers):
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": ticker,
            "outputsize": "full",
            "apikey": api_key,
        }
        try:
            payload = http_get(ALPHA_VANTAGE_URL, params=params).json()
        except SourceUnavailable as exc:
            failures.append(f"{ticker}: {exc}")
            continue
        series = payload.get("Time Series (Daily)")
        if not series:
            failures.append(f"{ticker}: {payload.get('Note') or payload.get('Information') or 'no series'}")
            if idx < len(tickers) - 1:
                time.sleep(sleep_seconds)
            continue
        frame = pd.DataFrame(series).T.reset_index().rename(columns={
            "index": "date", "1. open": "open", "2. high": "high",
            "3. low": "low", "4. close": "close",
            "5. adjusted close": "adj_close", "6. volume": "volume",
        })
        frame["ticker"] = ticker
        frames.append(frame)
        if idx < len(tickers) - 1:
            time.sleep(sleep_seconds)

    if not frames:
        raise SourceUnavailable("Alpha Vantage returned nothing; " + "; ".join(failures[:3]))

    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.date
    for col in ("open", "high", "low", "close", "adj_close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out[(out["date"] >= start) & (out["date"] <= end)]
    out["source"] = "alphavantage"
    return FetchResult(data=out, source="alphavantage",
                       source_url=ALPHA_VANTAGE_URL, notes=failures)


def local_csv_prices(path: str, tickers: list[str], start: date, end: date) -> FetchResult:
    """Offline source: a CSV the operator supplies.

    Columns: ticker,date,open,high,low,close,adj_close,volume
    Used for reproducible runs and for environments with no market-data egress.
    """
    from pathlib import Path

    csv_path = Path(path)
    if not csv_path.exists():
        raise SourceUnavailable(f"local price CSV not found: {csv_path}")
    df = pd.read_csv(csv_path, comment="#")
    required = {"ticker", "date", "adj_close"}
    if not required.issubset(df.columns):
        raise SourceUnavailable(f"{csv_path}: missing columns {required - set(df.columns)}")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    wanted = {t for t in tickers if t}
    if wanted:
        df = df[df["ticker"].isin(wanted)]
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df["source"] = f"local_csv:{csv_path.name}"
    return FetchResult(data=df, source=f"local_csv:{csv_path.name}",
                       source_url=str(csv_path))
