"""Trade disclosure sources, in the project's specified fallback order.

  1. Senate / House Stock Watcher bulk JSON   (free, no key)
  2. CapitolTrades  ->  QuiverQuant API       (QuiverQuant needs QUIVER_API_TOKEN)
  3. Raw efdsearch.senate.gov + House Clerk PTR filings

Each adapter returns rows in a common intermediate shape; `normalize.py` turns
that into the `trades` table. Column names differ per source, so each adapter
maps its own columns explicitly rather than relying on positional guesses.
"""

from __future__ import annotations

import json
import os

import pandas as pd

from .base import FetchResult, SourceUnavailable, http_get

# --------------------------------------------------------------------------
# 1. Stock Watcher bulk JSON
# --------------------------------------------------------------------------

SENATE_SW_URL = os.environ.get(
    "PTRACK_SENATE_SW_URL",
    "https://senate-stock-watcher-data.s3-us-west-2.amazonaws.com/aggregate/all_transactions.json",
)
HOUSE_SW_URL = os.environ.get(
    "PTRACK_HOUSE_SW_URL",
    "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
)

# Stock Watcher -> intermediate column names.
_SENATE_MAP = {
    "transaction_date": "trade_date",
    "disclosure_date": "disclosure_date",
    "ticker": "ticker",
    "asset_description": "asset_name",
    "asset_type": "asset_type_hint",
    "type": "transaction_type",
    "amount": "amount_range_text",
    "senator": "filer_name",
    "owner": "owner_code",
    "ptr_link": "source_url",
    "comment": "comment",
}
_HOUSE_MAP = {
    "transaction_date": "trade_date",
    "disclosure_date": "disclosure_date",
    "ticker": "ticker",
    "asset_description": "asset_name",
    "type": "transaction_type",
    "amount": "amount_range_text",
    "representative": "filer_name",
    "owner": "owner_code",
    "ptr_link": "source_url",
    "district": "district",
}


def _fetch_stock_watcher(url: str, chamber: str, colmap: dict) -> FetchResult:
    resp = http_get(url)
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"{url}: response was not JSON ({exc})") from exc
    if not isinstance(payload, list) or not payload:
        raise SourceUnavailable(f"{url}: unexpected payload shape")

    df = pd.DataFrame(payload)
    df["raw"] = [json.dumps(rec, default=str) for rec in payload]
    out = df.rename(columns={k: v for k, v in colmap.items() if k in df.columns})
    out["chamber"] = chamber
    if "source_url" not in out.columns:
        out["source_url"] = url
    out["source"] = f"{chamber}-stock-watcher"
    return FetchResult(data=out, source=f"{chamber}-stock-watcher", source_url=url)


def senate_stock_watcher() -> FetchResult:
    return _fetch_stock_watcher(SENATE_SW_URL, "senate", _SENATE_MAP)


def house_stock_watcher() -> FetchResult:
    return _fetch_stock_watcher(HOUSE_SW_URL, "house", _HOUSE_MAP)


def stock_watcher_both() -> FetchResult:
    """Both chambers. Succeeds if EITHER chamber answers; notes the other."""
    frames, notes, urls = [], [], []
    for label, fn in (("senate", senate_stock_watcher), ("house", house_stock_watcher)):
        try:
            res = fn()
            frames.append(res.data)
            urls.append(res.source_url)
        except SourceUnavailable as exc:
            notes.append(f"{label} chamber unavailable: {exc}")
    if not frames:
        raise SourceUnavailable("; ".join(notes) or "no Stock Watcher data")
    return FetchResult(
        data=pd.concat(frames, ignore_index=True),
        source="stock-watcher",
        source_url=" | ".join(urls),
        notes=notes,
    )


# --------------------------------------------------------------------------
# 2. CapitolTrades / QuiverQuant
# --------------------------------------------------------------------------

CAPITOLTRADES_URL = os.environ.get(
    "PTRACK_CAPITOLTRADES_URL", "https://bff.capitoltrades.com/trades"
)
QUIVER_URL = os.environ.get(
    "PTRACK_QUIVER_URL", "https://api.quiverquant.com/beta/bulk/congresstrading"
)

_CAPITOL_MAP = {
    "txDate": "trade_date",
    "filingDate": "disclosure_date",
    "_assetTicker": "ticker",
    "assetDescription": "asset_name",
    "txType": "transaction_type",
    "value": "amount_range_text",
    "owner": "owner_code",
}
_QUIVER_MAP = {
    "TransactionDate": "trade_date",
    "ReportDate": "disclosure_date",
    "Ticker": "ticker",
    "Name": "asset_name",
    "Transaction": "transaction_type",
    "Range": "amount_range_text",
    "Representative": "filer_name",
    "House": "chamber",
}


def capitoltrades(page_size: int = 500, max_pages: int = 200) -> FetchResult:
    """CapitolTrades' public BFF endpoint, paged.

    Unofficial/undocumented: treated strictly as a fallback and any schema drift
    surfaces as SourceUnavailable rather than as silently-wrong columns.
    """
    records: list[dict] = []
    for page in range(1, max_pages + 1):
        resp = http_get(f"{CAPITOLTRADES_URL}?page={page}&pageSize={page_size}")
        try:
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise SourceUnavailable(f"CapitolTrades page {page} not JSON ({exc})") from exc
        chunk = payload.get("data") if isinstance(payload, dict) else None
        if not chunk:
            break
        records.extend(chunk)
        meta = (payload.get("meta") or {}).get("paging") or {}
        if meta.get("totalPages") and page >= int(meta["totalPages"]):
            break
    if not records:
        raise SourceUnavailable("CapitolTrades returned no rows")

    df = pd.json_normalize(records)
    missing = [c for c in ("txDate", "txType") if c not in df.columns]
    if missing:
        raise SourceUnavailable(f"CapitolTrades schema drift; missing {missing}")
    df["raw"] = [json.dumps(r, default=str) for r in records]
    out = df.rename(columns={k: v for k, v in _CAPITOL_MAP.items() if k in df.columns})
    if "filer_name" not in out.columns:
        for cand in ("politician.fullName", "politician.name", "_politicianName"):
            if cand in out.columns:
                out["filer_name"] = out[cand]
                break
    out["source"] = "capitoltrades"
    out["source_url"] = CAPITOLTRADES_URL
    return FetchResult(data=out, source="capitoltrades", source_url=CAPITOLTRADES_URL)


def quiverquant() -> FetchResult:
    """QuiverQuant bulk congress trading. Requires QUIVER_API_TOKEN."""
    token = os.environ.get("QUIVER_API_TOKEN")
    if not token:
        raise SourceUnavailable("QUIVER_API_TOKEN is not set")
    resp = http_get(QUIVER_URL, headers={"Authorization": f"Bearer {token}",
                                         "Accept": "application/json"})
    payload = resp.json()
    if not payload:
        raise SourceUnavailable("QuiverQuant returned no rows")
    df = pd.DataFrame(payload)
    df["raw"] = [json.dumps(r, default=str) for r in payload]
    out = df.rename(columns={k: v for k, v in _QUIVER_MAP.items() if k in df.columns})
    out["source"] = "quiverquant"
    out["source_url"] = QUIVER_URL
    return FetchResult(data=out, source="quiverquant", source_url=QUIVER_URL)


# --------------------------------------------------------------------------
# 3. Primary filings: Senate EFD + House Clerk
# --------------------------------------------------------------------------

EFD_SEARCH = "https://efdsearch.senate.gov/search/"
HOUSE_CLERK = "https://disclosures-clerk.house.gov/FinancialDisclosure"


def senate_efd(**_) -> FetchResult:
    """Last-resort scrape of the Senate Electronic Financial Disclosure system.

    EFD requires accepting a click-through agreement that sets a session cookie,
    then serves results through a CSRF-protected POST. Reaching it also means
    honouring its terms of use and rate limits. This adapter deliberately stops
    at the handshake and reports what it needs rather than half-scraping: it is
    the documented escape hatch, enabled with PTRACK_ENABLE_EFD=1.
    """
    if os.environ.get("PTRACK_ENABLE_EFD") != "1":
        raise SourceUnavailable(
            "Senate EFD scraping is off by default (set PTRACK_ENABLE_EFD=1). It "
            "requires accepting the EFD terms-of-use click-through per session "
            "and respecting the site's rate limits."
        )
    session_probe = http_get(EFD_SEARCH)  # raises SourceUnavailable if blocked
    raise SourceUnavailable(
        "Senate EFD reachable (HTTP %s) but the PTR result set is served only "
        "behind the terms-of-use handshake; supply a session cookie via "
        "PTRACK_EFD_COOKIE to enable extraction." % session_probe.status_code
    )


def house_clerk(**_) -> FetchResult:
    """Last-resort House Clerk PTR source.

    The Clerk publishes a yearly ZIP of filing metadata plus one PDF per PTR.
    Many PTRs are scanned images, so extraction quality varies per filing and
    every extracted row must carry a lower confidence flag. Off by default.
    """
    if os.environ.get("PTRACK_ENABLE_HOUSE_CLERK") != "1":
        raise SourceUnavailable(
            "House Clerk PDF extraction is off by default "
            "(set PTRACK_ENABLE_HOUSE_CLERK=1). Rows it produces are OCR-derived "
            "and must be flagged lower-confidence than bulk-JSON rows."
        )
    raise SourceUnavailable(
        "House Clerk adapter requires pdfplumber and a per-year filing index; "
        "see README 'Primary filings' for the manual procedure."
    )


# --------------------------------------------------------------------------
# 4. Offline / operator-supplied CSV
# --------------------------------------------------------------------------

_LOCAL_REQUIRED = {"filer_name", "trade_date", "ticker", "transaction_type",
                   "amount_range_text"}


def local_csv_trades(path: str) -> FetchResult:
    """Disclosure rows from a CSV the operator supplies.

    For reproducible runs, for environments without egress to a bulk provider,
    and for data hand-extracted from primary filings. Optional columns
    (`sector`, `owner_code`, `disclosure_date`, `asset_name`, `asset_type_hint`,
    `chamber`, `filing_id`, `source`, `source_url`) are passed straight through;
    a `sector` supplied here is trusted and skips the sector resolver.
    """
    from pathlib import Path

    csv_path = Path(path)
    if not csv_path.exists():
        raise SourceUnavailable(f"local trades CSV not found: {csv_path}")
    df = pd.read_csv(csv_path, comment="#")
    missing = _LOCAL_REQUIRED - set(df.columns)
    if missing:
        raise SourceUnavailable(f"{csv_path}: missing columns {sorted(missing)}")
    df["raw"] = [json.dumps(r, default=str) for r in df.to_dict("records")]
    if "source" not in df.columns:
        df["source"] = f"local_csv:{csv_path.name}"
    if "source_url" not in df.columns:
        df["source_url"] = str(csv_path)
    return FetchResult(data=df, source=f"local_csv:{csv_path.name}",
                       source_url=str(csv_path))
