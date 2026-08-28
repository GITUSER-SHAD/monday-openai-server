# ptrack — public-disclosure trading analysis for U.S. officials

A re-runnable pipeline and analysis toolkit for stock trading disclosed by
members of Congress and the family members named on their filings, built
**exclusively from mandatory public disclosures** and public market price
series.

This document is the audit trail. It records every assumption, every data gap,
and every estimation method the pipeline uses. If a number in the output looks
precise, this file explains why it probably isn't.

---

## 1. What this does and does not claim

**What it measures.** Benchmark-relative performance of disclosed positions,
disclosure timeliness, sector concentration, and how often positions were
opened shortly before dated public events in the same sector.

**What it does not measure, and never asserts.**

- **Nothing here is evidence of insider trading, illegality, or intent.** The
  pipeline reports statistical patterns in public filings. Alpha and event
  timing are *correlational*. A person who trades energy names weekly will sit
  near energy events by arithmetic alone.
- **Event proximity is a base-rate artefact as much as a signal.** It is
  reported as a frequency statistic. The curated event list is a human
  selection, which itself determines what gets flagged.
- **Members do not necessarily direct these trades.** Many filings cover
  spouse-, child-, or advisor-managed accounts and blind-trust-like
  arrangements. The filer is the person with the reporting obligation, not
  necessarily the person who made the decision.
- **The composite score is a descriptive index, not a ranking of skill or of
  wrongdoing.** See §6 for why its own construction limits what it can mean.

---

## 2. Environment constraint (read this before interpreting any output)

This toolkit was built and validated in a sandbox whose egress policy blocks
essentially all external hosts. Verified 2026-08-28 with `python3 -m ptrack
doctor`:

| Category | Source | Result |
|---|---|---|
| Trades | Senate/House Stock Watcher bulk JSON | Reachable; returns **`AccessDenied`** — the project's public S3 buckets were retired upstream |
| Trades | CapitolTrades, QuiverQuant | Blocked by egress policy (CONNECT 403) |
| Trades | efdsearch.senate.gov, House Clerk | Blocked by egress policy (CONNECT 403) |
| Prices | yfinance/Yahoo, Alpha Vantage, Stooq, Polygon, Tiingo, Nasdaq, IEX | **All blocked** (CONNECT 403) |
| Events | Wikipedia, GDELT | Blocked by egress policy (CONNECT 403) |
| Roster | `unitedstates/congress-legislators` | **Works** — 537 current legislators ingested |

**Consequence.** No trade source and, critically, **no price source** is
reachable. Returns and alpha are the analytical core, and both require prices.
A ranked report over real, named officials therefore **could not be produced in
this environment**, and none was fabricated: invented performance figures and
event-proximity flags attached to real people would be far worse than no
report at all.

What exists instead is the complete toolkit, validated end to end against a
clearly-labelled synthetic fixture (§8). Run it where the sources are
reachable, or hand it exported CSVs via `--local-trades` / `--local-prices`,
and it produces the real report with no code changes.

`ptrack doctor` distinguishes the three reasons a source can fail — network
policy, retired upstream dataset, missing API key — because they need
different fixes.

---

## 3. Install and run

```bash
cd politician_trading
pip install -r requirements.txt

python3 -m ptrack doctor          # which sources are actually reachable?
python3 -m ptrack all             # ingest -> analyze -> report
```

Stages are independently runnable and idempotent:

```bash
python3 -m ptrack ingest  --events config/my_events.csv
python3 -m ptrack analyze --as-of 2026-08-01
python3 -m ptrack report
```

Useful flags:

| Flag | Purpose |
|---|---|
| `--local-trades FILE.csv` | Disclosure rows from a CSV; takes precedence over remote sources |
| `--local-prices FILE.csv` | Offline price series (`ticker,date,…,adj_close`) |
| `--events FILE.csv` | Curated event timeline (see §5.5) |
| `--as-of YYYY-MM-DD` | Mark date for positions still held |
| `--no-sector-lookup` | Use the sector cache and overrides only; no network |
| `--db`, `--out` | Database and output directory |

Configuration lives in `config/` — nothing tunable is hardcoded:
`benchmarks.yaml` (sector→ETF), `amount_ranges.yaml` (disclosure brackets),
`scoring.yaml` (weights, thresholds), `sector_overrides.csv`.

---

## 4. Data sources and fallback order

Each category tries sources in order and records **which one answered**, so
every figure can be traced. A failure is logged with its reason, never
silently swallowed, and the report cites the source that actually supplied the
data rather than assuming a default.

**Trades:** operator CSV → Senate/House Stock Watcher bulk JSON → CapitolTrades
→ QuiverQuant (`QUIVER_API_TOKEN`) → Senate EFD (`PTRACK_ENABLE_EFD=1`) →
House Clerk PTR PDFs (`PTRACK_ENABLE_HOUSE_CLERK=1`).

**Prices:** operator CSV → yfinance → Alpha Vantage (`ALPHAVANTAGE_API_KEY`).

**Roster:** `unitedstates/congress-legislators` (local checkout, else raw HTTPS).

**Events:** a curated CSV you build and review by hand (§5.5).

**Sectors:** `config/sector_overrides.csv` → cached resolver → yfinance issuer
metadata → unresolved.

The two primary-filing adapters are **off by default and deliberately
incomplete**. Senate EFD requires accepting a per-session terms-of-use
click-through; House PTRs are frequently scanned images whose OCR quality
varies per filing. Rows from either must be flagged lower-confidence than
bulk-JSON rows. They are the documented escape hatch, not a default path.

---

## 5. Methodology, assumptions and estimation methods

### 5.1 Amounts are ranges — every dollar figure is an estimate

Disclosures report brackets, never exact amounts. For each trade the pipeline
stores `amount_low`, `amount_high`, the verbatim `amount_range_text`, and
`amount_mid`, and stamps `amount_is_estimate = TRUE`.

- **Midpoint is used consistently** as the point estimate.
- The top bracket (`over $50,000,000`) is **open-ended and has no midpoint**.
  The pipeline uses its floor and sets `amount_bound_open = TRUE` so those rows
  can be excluded from, or sensitivity-tested in, any dollar-weighted total.
- An **unparseable** range yields `amount_mid = NULL`. The pipeline never
  invents a figure for a row it could not read.
- The report prints estimates as `~$X (est.)` beside the disclosed range, and a
  test asserts no bare dollar figure ever reaches the output.

**Every derived dollar total inherits this uncertainty.** A midpoint estimate
of a `$1,001–$15,000` bracket can be wrong by ±87%.

### 5.2 Two return metrics, never conflated

| Metric | Definition | Used for ranking? |
|---|---|---|
| `disclosure_drift_pct` | Price move from trade date → disclosure date | **No.** Measures reporting lag only |
| `position_return_pct` | Entry → matching exit, or entry → as-of date if still held | **Yes** |

Positions still held are marked `is_open = TRUE` and labelled **UNREALIZED**
at the point of use. They are marks, not booked gains.

### 5.3 Benchmarks and alpha

Every position is benchmarked against **SPY** and its **sector ETF** over the
*identical* window — same entry date, same exit date. What gets ranked is
`alpha = position_return − benchmark_return`, never raw return.

Assumptions:

- All return math uses **`adj_close`** (split- and dividend-adjusted), so a
  split inside a holding window cannot masquerade as a −50% return.
- A trade dated on a non-trading day uses the **first trading day on or after**
  that date — the earliest price actually observable. Open positions are marked
  at the **last trading day on or before** the as-of date.
- **Short/put asymmetry.** The default convention (`long_benchmark`) compares a
  position against *holding the index* over the same days, so a short is
  measured against a long benchmark. This is asymmetric by construction and is
  documented rather than hidden; `sign_matched` mode compares a short against
  shorting the index instead. Configurable.
- Sectors that cannot be resolved fall back to SPY and are flagged
  `sector_benchmark_is_fallback = TRUE`.
- The trading calendar is derived from the observed SPY price series, so it
  always matches the data actually held and needs no exchange-holiday package.

### 5.4 Netting (buy/sell pairs, not independent lines)

Disclosure lines in the same ticker by the same person are netted **FIFO** into
positions. Grouping is by `(person, ticker, instrument group)` — a call
purchase is never closed by a stock sale.

- Short sales invert the semantics: the **sale opens** and the covering
  **purchase closes**.
- **Lots are matched on estimated dollars, not shares**, because PTRs disclose
  no share count. A sale closes "the first N estimated dollars" of prior
  purchases. This affects how much *weight* a lot carries in aggregates, never
  the return itself, which comes from prices.
- **Partial exits** are tracked: the row shows the matched slice and says so,
  rather than printing a slice next to the full disclosed range as if they were
  the same figure.
- **Orphan closes** — sales with no matching prior purchase on record — are
  expected, not a bug: disclosure history begins mid-stream, so pre-existing
  holdings appear to be sold out of nowhere. They cannot yield a return (no
  entry price) and are excluded from metrics but counted in the run log.

### 5.5 Events and proximity

The event file is a CSV you build and review by hand from public timelines. It
is curated deliberately: an auto-scraped timeline would silently determine
which trades get flagged, and that selection must be inspectable.

```
event_id,date,category,sectors,description,source,source_url
```

`category` ∈ war, scandal, impeachment, trial, exec_death, legislation,
fed_action, sector_news. `sectors` is pipe-separated keys from
`benchmarks.yaml`. The loader warns about sectors that can never match a trade.

A position is flagged when it was **opened within 10 trading days before** an
event whose sectors include the trade's sector. Only the opening date is
tested. Weekends and holidays do not count toward the window.

### 5.6 Options

**Option returns are underlying proxies, not option P&L.** A periodic
transaction report discloses no strike and no expiry, so true option profit and
loss is not derivable from public data. The pipeline reports the
direction-adjusted move in the *underlying* and labels it
`return_basis = underlying_proxy_for_option` everywhere it appears. A long call
is long exposure, a long put is short exposure; written options invert, and are
only classified as written when the filing says so explicitly.

---

## 6. The composite score, and its limits

```
score = 0.4*mean_alpha_vs_spy
      + 0.3*win_rate
      + 0.2*median_alpha_vs_sector_etf
      + 0.1*event_proximity_rate
```

The formula lives in `config/scoring.yaml` and is echoed verbatim into every
report with its raw components, so any score can be recomputed by hand.

Two properties a reader must know — both stated in the report itself, not
buried here:

1. **Mixed units.** Alpha terms are return *fractions* (`0.08` = +8pp) while
   win rate and event-proximity rate are *rates* in `[0,1]`. Summing them makes
   one point of win rate worth a hundred points of alpha. A rank-normalised
   variant (`composite_score_normalized`) converts each component to its
   percentile within the eligible cohort before weighting, and is the fairer
   comparison. Both are reported.
2. **Event proximity enters as a positive term**, so trading near events raises
   the score. That is the specified weighting, not a finding about behaviour,
   and it is the reason the composite must not be read as a measure of skill or
   of misconduct.

**Eligibility.** A person needs at least `min_trades_for_ranking` (default 5)
analysed positions to be ranked. A 100% win rate over two trades is noise, and
letting it top a leaderboard would be the easiest way to make the whole
analysis misleading. Ineligible people are still scored and stored, just not
ranked.

**Per-person scope.** Metrics are computed over each person's top
`top_trades_per_person` (default 100) trades, selected by `largest` estimated
notional (configurable to `most_recent`). The report ranks the top
`report_top_n` (default 150).

---

## 7. Known data gaps

- **Family members are disclosed by role, not by name.** Filings mark an owner
  as `SP` (spouse), `DC` (dependent child) or `JT` (joint) without naming the
  individual. The pipeline models them as roles attached to the member's
  filing — it cannot name them, and does not. "Other relatives named on the
  same disclosure" are therefore only capturable where a source supplies a name;
  in practice bulk sources do not.
- **No share counts and no execution prices** are disclosed. All position
  weighting is dollar-approximate (§5.4).
- **No option strike or expiry** (§5.6).
- **Non-ticker assets** — mutual funds, bonds, private holdings, real estate —
  are kept in `trades` for the record but cannot be priced and are excluded
  from returns. The count is reported.
- **Sector coverage is imperfect.** Unresolved tickers fall back to SPY as
  their "sector" benchmark and are flagged.
- **Roster name matching is fuzzy.** Filer names are formatted differently
  across sources; unmatched filers are counted and listed in the run log, and
  their party/state/chamber will be missing.
- **Disclosure history begins mid-stream**, producing orphan closes (§5.4).
- **Amended filings.** The pipeline de-duplicates identical rows but does not
  attempt to supersede an original filing with its amendment; where a source
  publishes both, both are ingested.
- **Survivorship and delisting.** Tickers that no longer trade may have no
  price series; those positions are excluded from returns and counted as
  incomplete coverage rather than silently dropped into an average.
- **House PTR OCR quality** varies per filing (§4).

Coverage figures — positions dropped for missing prices, orphan closes,
unclassified sectors, unmatched filers — are surfaced in the report's
"Coverage and data quality" section and in the `run_log` table, never hidden
inside an average.

---

## 8. Validation

97 tests, no network, no external services:

```bash
python3 -m unittest discover tests -v
```

| Suite | Covers |
|---|---|
| `test_normalize.py` | Amount brackets incl. open-ended and unparseable, asset/direction parsing, tickers, dates, sector precedence |
| `test_netting.py` | FIFO ordering, partial exits, orphan closes, per-instrument grouping, short-sale semantics, cross-person isolation |
| `test_returns.py` | Trading-calendar lookups, direction adjustment, mark-to-last, both alpha conventions, drift separation |
| `test_events_and_scoring.py` | Window boundaries, sector matching, before-only, formula reproduction, eligibility threshold |
| `test_pipeline_e2e.py` | Full ingest→analyze→report with hand-computed alpha, report caveats, artifact writing |

A synthetic fixture exercises the whole pipeline offline:

```bash
python3 fixtures/make_fixture.py
python3 -m ptrack --db out/fixture.duckdb --out out/fixture_report all \
  --local-trades fixtures/synthetic_disclosures.csv \
  --local-prices fixtures/synthetic_prices.csv \
  --events fixtures/synthetic_events.csv --no-sector-lookup
```

> **The fixture is entirely invented.** Filer names are placeholders
> ("Synthetic Member Alpha"), tickers are placeholders (`ZZ**`), and prices are
> seeded random walks. No row corresponds to a real person, filing, or
> security. Numbers produced from it are meaningless as findings; its only
> purpose is to prove the pipeline runs correctly end to end.

Current fixture run: 480 disclosure lines → 404 netted positions (160 closed,
244 open), 23 event links, 28 people ranked.

---

## 9. Database schema

DuckDB, at `out/politician_trades.duckdb` by default.

| Table | Contents |
|---|---|
| `people` | Members and the family roles named on their filings; roster metadata and the roster that supplied it |
| `trades` | One row per disclosure line, with range bounds, midpoint estimate, instrument, direction, sector and verbatim source record |
| `prices` | Daily OHLC + `adj_close` for traded tickers and every benchmark |
| `benchmarks` | Sector → benchmark ETF mapping |
| `events` | Curated event timeline |
| `trade_event_links` | Trade↔event proximity matches with trading- and calendar-day distance |
| `positions` | FIFO-netted lots: open/close trade, matched slice, still-open flag |
| `trade_metrics` | Per-position returns, benchmark returns, alpha, drift, event flag, coverage flag |
| `person_metrics` | Per-person aggregates, score components, composite scores, rank, eligibility |
| `run_log` | Every ingest/analyze note, including every data-quality warning |

Fact-bearing tables carry `source` and `source_url`; dollar columns carry their
bounds and an is-estimate flag.

---

## 10. Outputs

`out/` contains:

- `ranked_report.md` — ranked table plus a profile per person: record counts,
  win rate, mean/median return and alpha, median disclosure lag, median drift
  (labelled as a lag metric), sector concentration, event-proximity rate,
  estimated notional, composite score, and the three largest-alpha positions
  with full context
- `ranked_people.csv` — the ranked cohort
- `person_metrics.csv` — all people including those below the ranking threshold
- `trade_metrics.csv` — one row per netted position, every metric per trade

The report opens with a "How to read this report" section carrying the estimate,
unrealized, option-proxy, drift, event-proximity and no-illegality caveats, and
a data-sources table citing what supplied each figure.
