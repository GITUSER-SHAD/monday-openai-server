"""Officials roster from the public `unitedstates/congress-legislators` dataset.

Supplies the `people` table's member rows: bioguide id, chamber, party, state,
district and term span. Family members are NOT in this dataset — they enter
`people` only when a disclosure names them, via `people_from_filings`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pandas as pd
import yaml

from .base import FetchResult, SourceUnavailable

REPO_URL = "https://github.com/unitedstates/congress-legislators"
RAW_BASE = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main"
DEFAULT_CHECKOUT = Path(os.environ.get(
    "PTRACK_LEGISLATORS_DIR", "/home/user/unitedstates/congress-legislators"))


def _load_yaml_source(filename: str, checkout: Path) -> tuple[list, str]:
    """Prefer a local checkout; fall back to the raw file over HTTPS."""
    local = checkout / filename
    if local.exists():
        with local.open() as fh:
            return yaml.safe_load(fh) or [], str(local)
    from .base import http_get
    url = f"{RAW_BASE}/{filename}"
    return yaml.safe_load(http_get(url).text) or [], url


def clone_legislators(dest: Path = DEFAULT_CHECKOUT) -> Path:
    """Shallow-clone the roster repo if it is not already present."""
    dest = Path(dest)
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(dest)],
        check=True, capture_output=True,
    )
    return dest


def congress_legislators(include_historical: bool = True,
                         checkout: Path = DEFAULT_CHECKOUT) -> FetchResult:
    files = ["legislators-current.yaml"]
    if include_historical:
        files.append("legislators-historical.yaml")

    rows: list[dict] = []
    urls: list[str] = []
    notes: list[str] = []
    for filename in files:
        try:
            payload, url = _load_yaml_source(filename, Path(checkout))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{filename}: {type(exc).__name__}: {exc}")
            continue
        urls.append(url)
        for entry in payload:
            rows.append(_flatten_legislator(entry, filename))

    if not rows:
        raise SourceUnavailable(
            "congress-legislators unavailable: " + "; ".join(notes))

    return FetchResult(data=pd.DataFrame(rows), source="congress-legislators",
                       source_url=" | ".join(urls), notes=notes)


def _flatten_legislator(entry: dict, filename: str) -> dict:
    ids = entry.get("id") or {}
    name = entry.get("name") or {}
    terms = entry.get("terms") or []
    last_term = terms[-1] if terms else {}
    first_term = terms[0] if terms else {}

    full_name = (
        name.get("official_full")
        or " ".join(p for p in (name.get("first"), name.get("last")) if p)
    )
    chamber = {"sen": "senate", "rep": "house"}.get(last_term.get("type"))
    district = last_term.get("district")

    return {
        "bioguide_id": ids.get("bioguide"),
        "full_name": full_name,
        "filer_name": full_name,
        "relation": "self",
        "chamber": chamber,
        "party": last_term.get("party"),
        "state": last_term.get("state"),
        "district": None if district is None else str(district),
        "term_start": first_term.get("start"),
        "term_end": last_term.get("end"),
        "is_current": filename == "legislators-current.yaml",
        "source": "congress-legislators",
        "source_url": f"{REPO_URL}/blob/main/{filename}",
    }
