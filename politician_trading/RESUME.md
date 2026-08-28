# Work-in-progress notes

Paused mid-build. This file records exactly where things stand so the next
session can pick up without re-deriving anything.

## Environment finding that shapes everything

This sandbox's egress policy blocks **every** live data host. Verified with
`python3 -m ptrack doctor` (re-run it to confirm):

| Source | Result |
|---|---|
| Senate/House Stock Watcher S3 | reachable, returns `AccessDenied` — the project's public buckets were retired |
| CapitolTrades, QuiverQuant | CONNECT tunnel 403 (egress policy) |
| efdsearch.senate.gov, House Clerk | CONNECT tunnel 403 (egress policy) |
| yfinance / Yahoo, Alpha Vantage, Stooq, Polygon, Tiingo, Nasdaq, IEX | CONNECT tunnel 403 (egress policy) |
| Wikipedia, GDELT, SEC | CONNECT tunnel 403 (egress policy) |
| `unitedstates/congress-legislators` (GitHub) | **works** — 537 current legislators |

So: **no trade source and no price source is reachable.** Without prices there
are no returns and no alpha, which is the analytical core. A ranked report over
real named officials therefore cannot be produced in this environment, and
inventing one is not an option — fabricated performance and "event proximity"
figures attached to real people would be worse than no report.

What was built instead: the complete, re-runnable toolkit, validated end to end
against a clearly-labelled synthetic fixture. Point it at reachable sources (or
supply `--local-trades` / `--local-prices` CSVs) and it produces the real report.

## Done

- `config/` — benchmarks (sector→ETF), STOCK Act amount brackets, scoring weights,
  sector overrides, event CSV template
- `ptrack/schema.sql` — people, trades, prices, benchmarks, events,
  trade_event_links + derived positions, trade_metrics, person_metrics, run_log
- `ptrack/config.py`, `db.py`, `normalize.py`
- `ptrack/sources/` — base fallback-chain runner, trades (Stock Watcher →
  CapitolTrades → Quiver → EFD/House Clerk → local CSV), prices (yfinance →
  Alpha Vantage → local CSV), roster (congress-legislators), events, sectors
- `ptrack/netting.py` — FIFO dollar-based lot matching, partial exits, orphan
  closes, per-instrument grouping, short-sale semantics
- `ptrack/returns.py` — PriceBook with trading-calendar lookups, direction-adjusted
  returns, disclosure drift kept separate, alpha with two benchmark conventions
- `ptrack/event_proximity.py` — 10-trading-day sector-matched windowing
- `ptrack/metrics.py`, `scoring.py`, `report.py`, `pipeline.py`, `cli.py`
- `fixtures/make_fixture.py` + generated synthetic CSVs
- Tests: `test_normalize.py` (21), `test_netting.py` (14), `test_returns.py` (21),
  `test_events_and_scoring.py` (17) — **73 passing**
- Full fixture run verified: 480 disclosure lines → 404 positions (160 closed /
  244 open), 23 event links, 28 people ranked, md + 3 CSVs written

Bugs found and fixed during validation (all real): CSV comment-line handling,
`itertuples` mangling underscore-prefixed columns, four computed metrics silently
dropped because they were missing from the table schema, timestamps rendering as
`2023-03-22 00:00:00`, and a partial FIFO slice being printed next to the full
disclosed range as if they were the same figure.

## Remaining

1. `tests/test_pipeline_e2e.py` — end-to-end test over a tiny inline dataset with
   hand-computable alpha (stub the roster source so it stays hermetic), asserting
   report disclaimers and CSV outputs exist.
2. `README.md` — assumptions, data gaps, estimation methods, per-figure source
   citation, the correlational framing, and the run instructions.
3. Optionally commit `out/fixture_report/` as validation evidence.

## Re-run

```bash
cd politician_trading
python3 -m unittest discover tests -v
python3 fixtures/make_fixture.py
python3 -m ptrack --db out/fixture.duckdb --out out/fixture_report all \
  --local-trades fixtures/synthetic_disclosures.csv \
  --local-prices fixtures/synthetic_prices.csv \
  --events fixtures/synthetic_events.csv --no-sector-lookup
```
