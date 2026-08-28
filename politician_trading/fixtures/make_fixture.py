#!/usr/bin/env python3
"""Generate a SYNTHETIC fixture dataset.

Everything this script writes is invented. The filer names are placeholders
("Synthetic Member Alpha"), the traded tickers are reserved-looking placeholders
(ZZ**), and the price series are seeded random walks. No row corresponds to a
real person, a real filing, or a real security.

Its only purpose is to exercise the pipeline end to end — netting, unrealized
marks, option and short handling, benchmark alignment, event proximity, scoring
and reporting — in an environment with no access to live disclosure or market
data. Numbers produced from it are meaningless as findings.

    python3 fixtures/make_fixture.py
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent
SEED = 20240817
START = date(2019, 1, 2)
END = date(2024, 12, 31)

# Placeholder tickers -> sector keys from config/benchmarks.yaml
TICKERS = {
    "ZZAA": "energy",
    "ZZBB": "defense",
    "ZZCC": "technology",
    "ZZDD": "financials",
    "ZZEE": "health_care",
    "ZZFF": "gold_mining",
    "ZZGG": "semiconductors",
    "ZZHH": "utilities",
    "ZZII": "consumer_discretionary",
    "ZZJJ": "real_estate",
}
BENCHMARKS = ["SPY", "XLE", "ITA", "XLK", "XLF", "XLV", "GDX", "SOXX", "XLU",
              "XLY", "XLRE"]

# (annual drift, annual vol) — deliberately varied so alpha is non-degenerate
DYNAMICS = {
    "SPY": (0.09, 0.16), "XLE": (0.07, 0.28), "ITA": (0.10, 0.22),
    "XLK": (0.15, 0.24), "XLF": (0.08, 0.21), "XLV": (0.07, 0.16),
    "GDX": (0.03, 0.34), "SOXX": (0.18, 0.30), "XLU": (0.05, 0.15),
    "XLY": (0.10, 0.23), "XLRE": (0.04, 0.20),
    "ZZAA": (0.11, 0.33), "ZZBB": (0.14, 0.25), "ZZCC": (0.19, 0.31),
    "ZZDD": (0.09, 0.26), "ZZEE": (0.06, 0.22), "ZZFF": (0.02, 0.41),
    "ZZGG": (0.22, 0.38), "ZZHH": (0.04, 0.17), "ZZII": (0.12, 0.28),
    "ZZJJ": (0.03, 0.24),
}

FILERS = [
    ("Synthetic Member Alpha", "senate"),
    ("Synthetic Member Bravo", "house"),
    ("Synthetic Member Charlie", "house"),
    ("Synthetic Member Delta", "senate"),
    ("Synthetic Member Echo", "house"),
    ("Synthetic Member Foxtrot", "house"),
    ("Synthetic Member Golf", "senate"),
    ("Synthetic Member Hotel", "house"),
]
OWNERS = ["SELF", "SELF", "SELF", "SP", "SP", "DC", "JT"]

AMOUNT_RANGES = [
    "$1,001 - $15,000", "$15,001 - $50,000", "$50,001 - $100,000",
    "$100,001 - $250,000", "$250,001 - $500,000", "$500,001 - $1,000,000",
    "$1,000,001 - $5,000,000", "over $50,000,000",
]
AMOUNT_WEIGHTS = [34, 26, 15, 10, 6, 5, 3, 1]

# (template, asset_type_hint, netting group, weight). The netting group must
# mirror ptrack.netting.asset_group: a call purchase is not closed by a put
# sale, so the generator has to track lots per group or every exit looks orphaned.
ASSET_FORMS = [
    ("{t} Common Stock", "Stock", "equity", 58),
    ("{t} Call Options", "Options", "option_call", 12),
    ("{t} Put Options", "Options", "option_put", 10),
    ("{t} Common Stock - short sale", "Stock", "short", 8),
    ("{t} Exchange Traded Fund", "ETF", "equity", 12),
]

EVENT_SPECS = [
    ("war", ["defense", "aerospace", "energy"], "Synthetic escalation in a regional conflict"),
    ("legislation", ["health_care", "pharmaceuticals"], "Synthetic drug-pricing bill reported out of committee"),
    ("fed_action", ["financials", "banks", "real_estate"], "Synthetic policy-rate decision"),
    ("sector_news", ["semiconductors", "technology"], "Synthetic export-control rule published"),
    ("scandal", ["financials"], "Synthetic accounting restatement at a large issuer"),
    ("legislation", ["energy", "utilities"], "Synthetic energy tax-credit package passes"),
    ("sector_news", ["gold_mining", "gold"], "Synthetic reserve-purchase announcement"),
    ("trial", ["consumer_discretionary"], "Synthetic antitrust verdict"),
    ("impeachment", ["broad_market"], "Synthetic impeachment proceeding opens"),
    ("exec_death", ["technology"], "Synthetic sudden CEO succession"),
]


def business_days(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def make_prices(days: list[date], rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    dt = 1.0 / 252.0
    for ticker in BENCHMARKS + list(TICKERS):
        mu, sigma = DYNAMICS[ticker]
        price = rng.uniform(25.0, 240.0)
        for day in days:
            shock = rng.gauss(0.0, 1.0)
            price *= math.exp((mu - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * shock)
            price = max(price, 0.75)
            intraday = abs(rng.gauss(0.0, 0.004))
            rows.append({
                "ticker": ticker,
                "date": day.isoformat(),
                "open": round(price * (1 - intraday / 2), 4),
                "high": round(price * (1 + intraday), 4),
                "low": round(price * (1 - intraday), 4),
                "close": round(price, 4),
                # Fixture prices are generated already adjusted; real sources
                # supply a distinct adj_close and the pipeline uses only that.
                "adj_close": round(price, 4),
                "volume": rng.randint(200_000, 9_000_000),
            })
    return rows


def make_events(days: list[date], rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    tradable = days[120:-40]
    for i, (category, sectors, description) in enumerate(EVENT_SPECS * 3, start=1):
        day = rng.choice(tradable)
        rows.append({
            "event_id": f"SYN-EV-{i:03d}",
            "date": day.isoformat(),
            "category": category,
            "sectors": "|".join(sectors),
            "description": f"[SYNTHETIC] {description}",
            "source": "synthetic-fixture",
            "source_url": "fixtures/make_fixture.py",
        })
    return sorted(rows, key=lambda r: r["date"])


def make_disclosures(days: list[date], events: list[dict],
                     rng: random.Random) -> list[dict]:
    day_index = {d: i for i, d in enumerate(days)}
    rows: list[dict] = []

    # Trades placed deliberately close to a matching event, so the proximity
    # detector has true positives to find in the fixture.
    planted: list[tuple[str, str, date]] = []
    for event in events:
        if rng.random() >= 0.35:
            continue
        sector = event["sectors"].split("|")[0]
        candidates = [t for t, s in TICKERS.items() if s == sector]
        if not candidates:
            continue
        event_day = date.fromisoformat(event["date"])
        idx = day_index.get(event_day)
        if idx is None or idx < 12:
            continue
        planted.append((rng.choice(FILERS)[0], rng.choice(candidates),
                        days[idx - rng.randint(1, 9)]))

    forms = [(f, hint, group) for f, hint, group, _ in ASSET_FORMS]
    form_weights = [w for _, _, _, w in ASSET_FORMS]

    for filer, chamber in FILERS:
        holdings: dict[tuple[str, str], list[date]] = {}
        owner_by_key: dict[tuple[str, str], str] = {}
        n_trades = rng.randint(28, 70)
        trade_days = sorted(rng.sample(days[60:-30], n_trades))

        for day in trade_days:
            ticker = rng.choice(list(TICKERS))
            form, hint, group = rng.choices(forms, weights=form_weights, k=1)[0]
            key = (ticker, group)
            open_lots = holdings.setdefault(key, [])
            owner = owner_by_key.setdefault(key, rng.choice(OWNERS))

            # For an explicit short sale the SALE opens the position and the
            # covering PURCHASE closes it; for everything else it is the reverse.
            if group == "short":
                opening, closing = "Sale", "Purchase"
            else:
                opening, closing = "Purchase", "Sale (Full)"

            if open_lots and rng.random() < 0.58:
                side = ("Sale (Partial)" if group != "short" and rng.random() < 0.25
                        else closing)
                open_lots.pop(0)
            elif not open_lots and rng.random() < 0.05:
                # Exit with nothing on record: exercises the orphan-close path
                # (a holding that pre-dates the disclosure history).
                side = closing
            else:
                side = opening
                open_lots.append(day)

            rows.append(_row(filer, chamber, ticker, form, hint, side, day,
                             owner, rng, day_index, days))

        for owner_filer, ticker, day in [p for p in planted if p[0] == filer]:
            owner = owner_by_key.setdefault((ticker, "equity"), rng.choice(OWNERS))
            rows.append(_row(owner_filer, chamber, ticker,
                             "{t} Common Stock", "Stock", "Purchase", day,
                             owner, rng, day_index, days))

    return sorted(rows, key=lambda r: (r["filer_name"], r["trade_date"]))


def _row(filer, chamber, ticker, form, hint, side, day, owner, rng,
         day_index, days) -> dict:
    idx = day_index[day]
    # Filing lag: most within the STOCK Act's 45-day window, a tail beyond it.
    lag = rng.randint(3, 44) if rng.random() < 0.86 else rng.randint(45, 320)
    disclosed = days[min(idx + lag, len(days) - 1)]
    return {
        "filer_name": filer,
        "chamber": chamber,
        "owner_code": owner,
        "trade_date": day.isoformat(),
        "disclosure_date": disclosed.isoformat(),
        "ticker": ticker,
        "asset_name": f"[SYNTHETIC] {form.format(t=ticker)}",
        "asset_type_hint": hint,
        "transaction_type": side,
        "amount_range_text": rng.choices(AMOUNT_RANGES, weights=AMOUNT_WEIGHTS, k=1)[0],
        "sector": TICKERS[ticker],
        "source": "synthetic-fixture",
        "source_url": "fixtures/make_fixture.py",
    }


def write_csv(path: Path, rows: list[dict], header_note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        fh.write(f"# {header_note}\n")
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):,} rows -> {path}")


def main() -> None:
    rng = random.Random(SEED)
    days = business_days(START, END)
    note = ("SYNTHETIC FIXTURE DATA - invented for pipeline testing. "
            "Not real filings, people, securities or prices.")
    write_csv(FIXTURE_DIR / "synthetic_prices.csv", make_prices(days, rng), note)
    events = make_events(days, rng)
    write_csv(FIXTURE_DIR / "synthetic_events.csv", events, note)
    write_csv(FIXTURE_DIR / "synthetic_disclosures.csv",
              make_disclosures(days, events, rng), note)


if __name__ == "__main__":
    main()
