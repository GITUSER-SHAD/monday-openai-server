"""Normalisation of raw disclosure rows into the `trades` schema.

Three jobs, each of which is a documented judgement call:
  1. Disclosed amount RANGE -> (low, high, midpoint ESTIMATE) + bounds retained.
  2. Free-text asset/transaction description -> asset_type + direction.
  3. Ticker -> sector.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

from .config import AmountBracket, Config, _norm_key

# --------------------------------------------------------------------------
# 1. Amounts
# --------------------------------------------------------------------------

_RANGE_RE = re.compile(
    r"\$?\s*([\d,]+(?:\.\d+)?)\s*(?:-|–|—|to)\s*\$?\s*([\d,]+(?:\.\d+)?)", re.I
)
_OVER_RE = re.compile(r"(?:over|above|more than|\+)\s*\$?\s*([\d,]+)", re.I)


def parse_amount_range(text: str | None, cfg: Config) -> dict:
    """Map a disclosed amount range to bounds and a midpoint ESTIMATE.

    Returns amount_mid = NULL when the range cannot be parsed at all — we never
    guess a dollar figure for an unparseable row.
    """
    blank = {
        "amount_range_text": text,
        "amount_low": None,
        "amount_high": None,
        "amount_mid": None,
        "amount_is_estimate": True,
        "amount_bound_open": False,
    }
    if not text or not str(text).strip():
        return blank
    raw = str(text).strip()

    canonical = cfg.bracket_aliases.get(_norm_key(raw), raw)
    for bracket in cfg.brackets:
        if _norm_key(bracket.text) == _norm_key(canonical):
            return _from_bracket(bracket, raw)

    m = _RANGE_RE.search(raw)
    if m:
        low = float(m.group(1).replace(",", ""))
        high = float(m.group(2).replace(",", ""))
        if high < low:
            low, high = high, low
        return {
            "amount_range_text": raw,
            "amount_low": low,
            "amount_high": high,
            "amount_mid": (low + high) / 2.0,
            "amount_is_estimate": True,
            "amount_bound_open": False,
        }

    m = _OVER_RE.search(raw)
    if m:
        low = float(m.group(1).replace(",", ""))
        return {
            "amount_range_text": raw,
            "amount_low": low,
            "amount_high": None,
            "amount_mid": low,           # floor, not a midpoint — flagged below
            "amount_is_estimate": True,
            "amount_bound_open": True,
        }
    return blank


def _from_bracket(bracket: AmountBracket, raw: str) -> dict:
    return {
        "amount_range_text": raw,
        "amount_low": bracket.low,
        "amount_high": bracket.high,
        "amount_mid": bracket.midpoint,
        "amount_is_estimate": True,
        "amount_bound_open": bracket.is_open_ended,
    }


# --------------------------------------------------------------------------
# 2. Asset type / direction / side
# --------------------------------------------------------------------------

_PUT_RE = re.compile(r"\bput\b|\bputs\b", re.I)
_CALL_RE = re.compile(r"\bcall\b|\bcalls\b", re.I)
_SHORT_RE = re.compile(r"\bshort\s+(sale|sell|position)\b|\bsold\s+short\b", re.I)
_ETF_RE = re.compile(r"\betf\b|\bindex fund\b|\bexchange[- ]traded\b", re.I)
_WRITE_RE = re.compile(r"\bwrit(e|ten|ing)\b|\bsold to open\b", re.I)

_BUY_TOKENS = {"p", "purchase", "buy", "bought", "p (partial)", "purchase (partial)"}
_SELL_TOKENS = {
    "s", "sale", "sell", "sold", "s (partial)", "sale (partial)",
    "sale (full)", "s (full)", "sold (partial)", "sold (full)",
}
_EXCHANGE_TOKENS = {"e", "exchange", "exchanged"}


def parse_side(transaction_type: str | None) -> str:
    if not transaction_type:
        return "unknown"
    t = str(transaction_type).strip().lower()
    if t in _BUY_TOKENS or t.startswith("purchase") or t.startswith("buy"):
        return "buy"
    if t in _SELL_TOKENS or t.startswith("sale") or t.startswith("sell") or t.startswith("sold"):
        return "sell"
    if t in _EXCHANGE_TOKENS or t.startswith("exchange"):
        return "exchange"
    return "unknown"


def parse_asset(asset_description: str | None, asset_type_hint: str | None = None) -> tuple[str, str]:
    """Return (asset_type, direction).

    direction is the position's economic exposure to the UNDERLYING:
      long  — equity/ETF purchase, long call
      short — short sale, long put
    A written (sold-to-open) call is short exposure; a written put is long
    exposure. We only classify writes when the filing says so explicitly,
    because most PTRs do not distinguish opening from closing an option.
    """
    text = " ".join(str(x) for x in (asset_description, asset_type_hint) if x)
    if not text.strip():
        return "unknown", "long"

    written = bool(_WRITE_RE.search(text))
    if _PUT_RE.search(text):
        return "option_put", "long" if written else "short"
    if _CALL_RE.search(text):
        return "option_call", "short" if written else "long"
    if _SHORT_RE.search(text):
        return "short", "short"
    if _ETF_RE.search(text):
        return "etf", "long"
    if asset_type_hint and "stock" in str(asset_type_hint).lower():
        return "equity", "long"
    return "equity", "long"


# --------------------------------------------------------------------------
# 3. Tickers and sectors
# --------------------------------------------------------------------------

_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,6}$")
_BAD_TICKERS = {"--", "N/A", "NA", "NONE", "", "-", "UNKNOWN"}


def clean_ticker(ticker: str | None) -> str | None:
    if ticker is None:
        return None
    t = str(ticker).strip().upper()
    t = t.split()[0] if t else t
    if t in _BAD_TICKERS or not _TICKER_RE.match(t):
        return None
    return t


def resolve_sector(ticker: str | None, cfg: Config,
                   resolver: dict[str, str] | None = None) -> tuple[str | None, str]:
    """Return (sector, sector_source). Override file wins, then resolver map."""
    if not ticker:
        return None, "fallback"
    if ticker in cfg.sector_overrides:
        return cfg.sector_overrides[ticker], "override"
    if resolver and ticker in resolver:
        return resolver[ticker], "resolver"
    return None, "fallback"


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %B %Y", "%B %d, %Y")


def parse_date(value) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "--"}:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(text).date()
    except Exception:
        return None
