"""Command-line entry point.

  python -m triage enumerate  [--config triage-config.json]
  python -m triage inventory  [--drive E:\\] ...
  python -m triage hash
  python -m triage classify
  python -m triage report
  python -m triage all        (inventory -> hash -> classify -> report)

Every command is read-only with respect to scanned drives and resumable:
interrupt at any point and re-run the same command. Verbose progress goes to
log files under log_dir; the console only prints warnings and a short summary.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .util import guard_output_dirs, load_config, setup_logging
from . import volumes as volumes_mod
from .inventory import run_inventory
from .hashing import (
    collect_prefix_groups, collect_size_census, run_full_stage,
    run_prefix_stage,
)
from .dupes import DReference
from .classify import run_classify
from .report import run_reports


def _resolve_roots(cfg, args, logger):
    roots = None
    if args.drive:
        roots = list(args.drive)
    elif cfg["scan_roots"]:
        roots = list(cfg["scan_roots"])
    else:
        scope_path = os.path.join(cfg["output_dir"], "scope.json")
        if os.path.exists(scope_path):
            roots = volumes_mod.load_approved_scope(scope_path) or None
    if not roots:
        raise SystemExit(
            "No scan roots. Run `python -m triage enumerate`, review/approve "
            "the generated scope.json (Phase 0 check-in), then re-run - or "
            "set scan_roots in the config / pass --drive.")
    guard_output_dirs({**cfg, "scan_roots": roots})
    return roots


def _dref(cfg, logger):
    return DReference.load(cfg["d_reference_csv"], logger)


def cmd_enumerate(cfg, args, logger):
    vols, scope_path = volumes_mod.run_enumerate(cfg, logger)
    print(volumes_mod.format_table(vols))
    print(f"\nPhase 0 check-in: review {scope_path} - set \"in_scope\" "
          f"per volume, then run `python -m triage all`.")
    print("C:, D: and network mounts are excluded by default.")
    return 0


def cmd_inventory(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    for root in roots:
        if not os.path.isdir(root):
            logger.warning("scan root %s not present; skipping "
                           "(re-run when the drive is attached)", root)
            continue
        new, total = run_inventory(cfg, root, logger, args.max_files)
        print(f"{root}: inventory rows +{new:,} (total {total:,})")
    return 0


def cmd_hash(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    dref = _dref(cfg, logger)
    census = collect_size_census(cfg, roots, dref, logger)
    for root in roots:
        n = run_prefix_stage(cfg, root, census, dref, logger, args.max_files)
        print(f"{root}: prefix-hashed {n:,} candidate files")
    groups = collect_prefix_groups(cfg, roots)
    for root in roots:
        n = run_full_stage(cfg, root, groups, dref, logger, args.max_files)
        print(f"{root}: full-hashed {n:,} files")
    return 0


def _set_activity_cutoff(cfg):
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=int(cfg["active_project_days"]))
    cfg["_activity_cutoff_iso"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_classify(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    _set_activity_cutoff(cfg)
    dref = _dref(cfg, logger)
    stats = run_classify(cfg, roots, dref, logger)
    for root, counts in stats.items():
        print(f"{root}: " + ", ".join(
            f"{k}={v:,}" for k, v in sorted(counts.items())))
    return 0


def cmd_report(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    outs = run_reports(cfg, roots, logger)
    for o in outs:
        print(f"wrote {o}")
    return 0


def cmd_all(cfg, args, logger):
    cmd_inventory(cfg, args, logger)
    cmd_hash(cfg, args, logger)
    cmd_classify(cfg, args, logger)
    cmd_report(cfg, args, logger)
    return 0


COMMANDS = {
    "enumerate": cmd_enumerate,
    "inventory": cmd_inventory,
    "hash": cmd_hash,
    "classify": cmd_classify,
    "report": cmd_report,
    "all": cmd_all,
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="triage",
        description=f"Read-only external drive triage v{__version__}")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--config", default="", help="path to triage-config.json")
    ap.add_argument("--drive", action="append", default=[],
                    help="scan root (repeatable); overrides scope/config")
    ap.add_argument("--output-dir", default="", help="override output_dir")
    ap.add_argument("--log-dir", default="", help="override log_dir")
    ap.add_argument("--d-reference", default="",
                    help="override d_reference_csv")
    ap.add_argument("--max-files", type=int, default=None,
                    help="stop each stage after N new rows (testing/resume)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.output_dir:
        cfg["output_dir"] = args.output_dir
    if args.log_dir:
        cfg["log_dir"] = args.log_dir
    if args.d_reference:
        cfg["d_reference_csv"] = args.d_reference
    if args.drive:
        cfg["scan_roots"] = list(args.drive)

    # Guard BEFORE creating any directory or log file. For scanning commands
    # the roots are fully resolved (scope.json included) right here, so a
    # guard violation aborts before a single byte lands anywhere; `enumerate`
    # has no roots yet, but guard_output_dirs still enforces the Windows
    # system-drive rule for the output/log dirs themselves.
    if args.command == "enumerate":
        guard_output_dirs(cfg)
    else:
        _resolve_roots(cfg, args, None)  # raises before any write on trouble

    os.makedirs(cfg["output_dir"], exist_ok=True)
    logger = setup_logging(cfg["log_dir"], f"triage-{args.command}")
    logger.info("triage v%s command=%s config=%s", __version__, args.command,
                args.config or "(defaults)")
    try:
        return COMMANDS[args.command](cfg, args, logger)
    except KeyboardInterrupt:
        logger.warning("interrupted - state is resumable; re-run the same "
                       "command to continue")
        return 130


if __name__ == "__main__":
    sys.exit(main())
