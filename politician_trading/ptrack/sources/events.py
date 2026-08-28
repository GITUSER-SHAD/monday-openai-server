"""Curated event timeline.

The event file is a CSV the operator builds and reviews by hand from public
timelines (Wikipedia, GDELT, Federal Register, Fed calendars). It is curated on
purpose: an automatically scraped timeline would silently determine which trades
get flagged for "event proximity", and that selection has to be inspectable.

Columns: event_id,date,category,sectors,description,source,source_url
  category : war|scandal|impeachment|trial|exec_death|legislation|fed_action|sector_news
  sectors  : pipe-separated sector keys from config/benchmarks.yaml
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import FetchResult, SourceUnavailable

REQUIRED = {"event_id", "date", "category", "sectors", "description"}
VALID_CATEGORIES = {
    "war", "scandal", "impeachment", "trial", "exec_death",
    "legislation", "fed_action", "sector_news",
}


def curated_csv(path: str | Path, valid_sectors: set[str] | None = None) -> FetchResult:
    path = Path(path)
    if not path.exists():
        raise SourceUnavailable(f"event CSV not found: {path}")
    df = pd.read_csv(path, comment="#")
    missing = REQUIRED - set(df.columns)
    if missing:
        raise SourceUnavailable(f"{path}: missing columns {sorted(missing)}")

    notes: list[str] = []
    df["event_date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    bad_dates = int(df["event_date"].isna().sum())
    if bad_dates:
        notes.append(f"{bad_dates} event rows dropped: unparseable date")
        df = df.dropna(subset=["event_date"])

    bad_cat = sorted(set(df["category"]) - VALID_CATEGORIES)
    if bad_cat:
        notes.append(f"unrecognised event categories kept as-is: {bad_cat}")

    if valid_sectors:
        unknown: set[str] = set()
        for cell in df["sectors"].fillna(""):
            unknown |= {s.strip() for s in str(cell).split("|") if s.strip()} - valid_sectors
        if unknown:
            notes.append(
                f"event sectors not in benchmarks.yaml (will never match a trade): "
                f"{sorted(unknown)}"
            )

    for col in ("source", "source_url"):
        if col not in df.columns:
            df[col] = "curated"
    df["source"] = df["source"].fillna("curated")

    return FetchResult(data=df, source="curated-events", source_url=str(path), notes=notes)
