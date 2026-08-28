"""Ticker -> sector resolution.

Order of precedence:
  1. config/sector_overrides.csv   (hand-checked, always wins)
  2. cached resolver file          (out/sector_cache.csv)
  3. yfinance issuer metadata      (network)
  4. unresolved -> sector NULL, benchmarked against the fallback ETF and flagged

The mapping from a vendor's sector label to this project's sector keys is
explicit below rather than fuzzy-matched, because a mis-mapped sector silently
changes which ETF a trade is benchmarked against.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import SourceUnavailable

# yfinance / GICS-style sector label -> config/benchmarks.yaml sector key
VENDOR_SECTOR_MAP = {
    "energy": "energy",
    "financial services": "financials",
    "financials": "financials",
    "technology": "technology",
    "information technology": "technology",
    "communication services": "communication_services",
    "healthcare": "health_care",
    "health care": "health_care",
    "industrials": "industrials",
    "consumer cyclical": "consumer_discretionary",
    "consumer discretionary": "consumer_discretionary",
    "consumer defensive": "consumer_staples",
    "consumer staples": "consumer_staples",
    "utilities": "utilities",
    "real estate": "real_estate",
    "basic materials": "materials",
    "materials": "materials",
}


def load_cache(path: Path) -> dict[str, str]:
    if not Path(path).exists():
        return {}
    df = pd.read_csv(path)
    if not {"ticker", "sector"}.issubset(df.columns):
        return {}
    return {str(r.ticker).upper(): str(r.sector)
            for r in df.itertuples(index=False) if pd.notna(r.sector)}


def save_cache(path: Path, mapping: dict[str, str]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        sorted(mapping.items()), columns=["ticker", "sector"]
    ).to_csv(path, index=False)


def resolve_with_yfinance(tickers: list[str], cache: dict[str, str],
                          limit: int | None = None) -> tuple[dict[str, str], list[str]]:
    """Look up unresolved tickers' sectors. Returns (mapping, notes)."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SourceUnavailable("yfinance is not installed") from exc

    todo = [t for t in dict.fromkeys(tickers) if t and t not in cache]
    if limit is not None:
        todo = todo[:limit]
    resolved: dict[str, str] = {}
    notes: list[str] = []
    for ticker in todo:
        try:
            info = yf.Ticker(ticker).get_info()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{ticker}: {type(exc).__name__}")
            continue
        vendor = (info or {}).get("sector")
        if not vendor:
            notes.append(f"{ticker}: no sector reported")
            continue
        key = VENDOR_SECTOR_MAP.get(str(vendor).strip().lower())
        if key:
            resolved[ticker] = key
        else:
            notes.append(f"{ticker}: unmapped vendor sector '{vendor}'")
    return resolved, notes
