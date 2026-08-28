"""Command line interface.

    python -m ptrack doctor      # probe every source, report what is reachable
    python -m ptrack ingest      # fetch + normalise into the database
    python -m ptrack analyze     # net, price, benchmark, score
    python -m ptrack report      # write ranked_report.md + CSVs
    python -m ptrack all         # ingest + analyze + report
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import db, pipeline
from .config import DEFAULT_DB, DEFAULT_OUT, load_config
from .sources import events as events_src
from .sources import prices as prices_src
from .sources import roster as roster_src
from .sources import trades as trades_src
from .sources.base import SourceUnavailable


def _parse_date(value: str | None):
    return None if not value else datetime.strptime(value, "%Y-%m-%d").date()


def cmd_doctor(args) -> int:
    """Probe each source in the fallback chain and report reachability.

    Written for exactly the situation where a run produces nothing: it separates
    'the network will not let me out' from 'the upstream dataset is gone' from
    'this needs an API key', which need different fixes.
    """
    cfg = load_config(args.config)
    probes = [
        ("trades", "senate-stock-watcher", lambda: trades_src.senate_stock_watcher()),
        ("trades", "house-stock-watcher", lambda: trades_src.house_stock_watcher()),
        ("trades", "capitoltrades", lambda: trades_src.capitoltrades(page_size=10, max_pages=1)),
        ("trades", "quiverquant", lambda: trades_src.quiverquant()),
        ("trades", "senate-efd", lambda: trades_src.senate_efd()),
        ("trades", "house-clerk", lambda: trades_src.house_clerk()),
        ("roster", "congress-legislators", lambda: roster_src.congress_legislators(False)),
        ("prices", "yfinance", lambda: prices_src.yfinance_prices(
            [cfg.market_benchmark], date(2024, 1, 2), date(2024, 1, 10))),
        ("prices", "alphavantage", lambda: prices_src.alpha_vantage_prices(
            [cfg.market_benchmark], date(2024, 1, 2), date(2024, 1, 10))),
    ]
    if args.events:
        probes.append(("events", f"curated:{Path(args.events).name}",
                       lambda: events_src.curated_csv(args.events, set(cfg.sector_etfs))))

    width = max(len(name) for _, name, _ in probes) + 2
    failures = 0
    print(f"{'CATEGORY':<9} {'SOURCE':<{width}} STATUS")
    for category, name, probe in probes:
        try:
            result = probe()
            status = (f"OK — {len(result.data):,} rows" if result.ok
                      else "REACHABLE but empty")
        except SourceUnavailable as exc:
            status = f"UNAVAILABLE — {exc}"
            failures += 1
        except Exception as exc:  # noqa: BLE001
            status = f"ERROR — {type(exc).__name__}: {exc}"
            failures += 1
        print(f"{category:<9} {name:<{width}} {status}")

    print()
    print(f"{len(probes) - failures}/{len(probes)} sources usable.")
    if failures:
        print("A source can be unusable for three different reasons — network "
              "egress policy, a retired upstream dataset, or a missing API key. "
              "The message above says which.")
    return 0


def cmd_ingest(args) -> int:
    cfg = load_config(args.config)
    con = db.connect(args.db)
    run_id = db.new_run_id()
    summary = pipeline.ingest(
        con, cfg, run_id,
        events_csv=Path(args.events) if args.events else None,
        local_prices_csv=Path(args.local_prices) if args.local_prices else None,
        local_trades_csv=Path(args.local_trades) if args.local_trades else None,
        resolve_sectors=not args.no_sector_lookup,
        price_start=_parse_date(args.price_start),
    )
    con.close()
    print(f"\nrun_id={run_id}  trades={summary.get('trades_ingested', 0)}")
    return 0 if summary.get("trades_ingested") else 1


def cmd_analyze(args) -> int:
    cfg = load_config(args.config)
    con = db.connect(args.db)
    run_id = db.new_run_id()
    summary = pipeline.analyze(con, cfg, run_id, as_of=_parse_date(args.as_of))
    con.close()
    print(f"\nrun_id={run_id}  positions={summary.get('positions', 0)}  "
          f"eligible={summary.get('eligible', 0)}")
    return 0 if summary.get("positions") else 1


def cmd_report(args) -> int:
    cfg = load_config(args.config)
    con = db.connect(args.db)
    run_id = args.run_id or db.new_run_id()
    paths = pipeline.build_report(con, cfg, run_id, Path(args.out),
                                  as_of=_parse_date(args.as_of))
    con.close()
    for label, path in paths.items():
        print(f"{label:<16} {path}")
    return 0


def cmd_all(args) -> int:
    cfg = load_config(args.config)
    con = db.connect(args.db)
    run_id = db.new_run_id()
    ingest_summary = pipeline.ingest(
        con, cfg, run_id,
        events_csv=Path(args.events) if args.events else None,
        local_prices_csv=Path(args.local_prices) if args.local_prices else None,
        local_trades_csv=Path(args.local_trades) if args.local_trades else None,
        resolve_sectors=not args.no_sector_lookup,
        price_start=_parse_date(args.price_start),
    )
    if not ingest_summary.get("trades_ingested"):
        print("\nIngest produced no trades. Run `python -m ptrack doctor` to see "
              "which sources are reachable.", file=sys.stderr)
        con.close()
        return 1
    analysis = pipeline.analyze(con, cfg, run_id, as_of=_parse_date(args.as_of))
    paths = pipeline.build_report(con, cfg, run_id, Path(args.out),
                                  as_of=analysis.get("as_of"))
    con.close()
    print()
    for label, path in paths.items():
        print(f"{label:<16} {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ptrack", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB path")
    parser.add_argument("--config", default=None, help="config directory")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_ingest_args(p):
        p.add_argument("--events", default=None, help="curated events CSV")
        p.add_argument("--local-prices", default=None,
                       help="offline price CSV (ticker,date,...,adj_close)")
        p.add_argument("--local-trades", default=None,
                       help="offline disclosure CSV; takes precedence over remote sources")
        p.add_argument("--price-start", default=None, help="YYYY-MM-DD")
        p.add_argument("--no-sector-lookup", action="store_true",
                       help="skip network sector resolution; use cache + overrides only")

    p_doctor = sub.add_parser("doctor", help="probe source reachability")
    p_doctor.add_argument("--events", default=None)
    p_doctor.set_defaults(func=cmd_doctor)

    p_ingest = sub.add_parser("ingest", help="fetch and normalise source data")
    add_ingest_args(p_ingest)
    p_ingest.set_defaults(func=cmd_ingest)

    p_analyze = sub.add_parser("analyze", help="net, price, benchmark and score")
    p_analyze.add_argument("--as-of", default=None, help="YYYY-MM-DD mark date")
    p_analyze.set_defaults(func=cmd_analyze)

    p_report = sub.add_parser("report", help="write ranked report and CSVs")
    p_report.add_argument("--as-of", default=None)
    p_report.add_argument("--run-id", default=None)
    p_report.set_defaults(func=cmd_report)

    p_all = sub.add_parser("all", help="ingest + analyze + report")
    add_ingest_args(p_all)
    p_all.add_argument("--as-of", default=None)
    p_all.set_defaults(func=cmd_all)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.config is None:
        from .config import CONFIG_DIR
        args.config = CONFIG_DIR
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
