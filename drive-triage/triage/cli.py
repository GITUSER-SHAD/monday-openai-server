"""Command-line entry point.

  python -m triage enumerate  [--config triage-config.json]
  python -m triage probe      --drive \\\\server\\share   (reachability check)
  python -m triage inventory  [--drive E:\\ | --drive \\\\server\\share] ...
  python -m triage hash
  python -m triage classify
  python -m triage report
  python -m triage all        (inventory -> hash -> classify -> report)
  python -m triage crossdrive [--workspace C:\\DEV\\triage]
  python -m triage hashgaps   [--workspace C:\\DEV\\triage] [--run NAME]

Every command is read-only with respect to scanned drives and resumable:
interrupt at any point and re-run the same command. Verbose progress goes to
log files under log_dir; the console only prints warnings and a short summary.
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .util import (
    IS_WINDOWS, atomic_write_json, drive_slug, fmt_gb, guard_output_dirs,
    is_unc, is_under, load_config, load_json, normalize_root, setup_logging,
)
from . import volumes as volumes_mod
from .inventory import inventory_paths, run_inventory
from .hashing import (
    check_hash_marker, collect_prefix_groups, collect_size_census,
    prune_stale_hashes, run_full_stage, run_prefix_stage, write_hash_marker,
)
from .dupes import DReference
from .classify import run_classify
from .report import run_reports
from . import crossdrive
from . import hashgaps


def _resolve_roots(cfg, args, logger):
    raw = None
    if args.drive:
        raw = list(args.drive)
    elif cfg["scan_roots"]:
        raw = list(cfg["scan_roots"])
    else:
        scope_path = os.path.join(cfg["output_dir"], "scope.json")
        if os.path.exists(scope_path):
            raw = volumes_mod.load_approved_scope(scope_path) or None
    if not raw:
        raise SystemExit(
            "No scan roots. Run `python -m triage enumerate`, review/approve "
            "the generated scope.json (Phase 0 check-in), then re-run - or "
            "set scan_roots in the config / pass --drive.")

    roots, seen = [], set()
    for r in raw:
        n = normalize_root(r)
        if n.upper().rstrip("\\/") in ("C:", "D:"):
            raise SystemExit(
                f"scan root {r!r}: C: and D: are excluded from triage by "
                f"design (D: is mid-reorg; C: is the system drive).")
        if n.startswith("\\\\") and not is_unc(n):
            raise SystemExit(
                f"scan root {r!r} looks like a network path but is not a "
                f"complete share. Use the form \\\\server\\share, e.g. "
                f"\\\\100.76.11.114\\fastwork")
        k = n.casefold() if IS_WINDOWS else n
        if k not in seen:
            seen.add(k)
            roots.append(n)
    for a in roots:
        for b in roots:
            if a is not b and is_under(a, b):
                raise SystemExit(
                    f"scan roots overlap: {a!r} lies inside {b!r}. "
                    f"Overlapping roots would inventory the same files "
                    f"twice and fabricate self-duplicates; scan just {b!r}.")
    guard_output_dirs({**cfg, "scan_roots": roots})
    return roots


def _verify_volume_identity(cfg, roots, logger):
    """Bind per-drive state files to the physical volume, not the letter:
    if a DIFFERENT drive is mounted at the same letter later, refuse to mix
    its files into the old inventory."""
    if not IS_WINDOWS:
        return
    sigs = volumes_mod.volume_signatures(logger)
    for root in roots:
        letter = root.rstrip("\\/").upper()
        sig = sigs.get(letter)
        if not sig:
            continue
        meta_path = inventory_paths(cfg, root)["csv"].replace(
            ".csv", ".meta.json")
        prev = load_json(meta_path)
        if prev is None:
            atomic_write_json(meta_path, sig)
        elif (prev.get("label"), prev.get("size")) != \
                (sig.get("label"), sig.get("size")):
            raise SystemExit(
                f"{root} now holds volume {sig!r} but existing triage state "
                f"was built from {prev!r}. A different drive is mounted at "
                f"this letter - move or delete the old inventory-"
                f"{inventory_paths(cfg, root)['slug']}* outputs first.")


def _require_reachable(roots, logger):
    """Fail loudly when a named target cannot be reached, instead of quietly
    scanning nothing. A network share that is offline, refusing credentials,
    or (when running elevated) mapped only in the non-elevated session is
    the common cause."""
    missing = [r for r in roots if not os.path.isdir(r)]
    if not missing:
        return
    if len(missing) == len(roots):
        detail = "\n".join(f"  {m}" for m in missing)
        hint = ""
        if any(is_unc(m) for m in missing):
            hint = (
                "\n\nThis is a network path. Check that the NAS is on and "
                "reachable, and that the share name is spelled exactly "
                "right. Note that a drive letter mapped in your normal "
                "session (U:, V:, X:, Y:, Z:) does NOT exist in an "
                "Administrator session - that is why the full "
                "\\\\server\\share path is used here.")
        raise SystemExit(f"cannot reach:\n{detail}{hint}")
    for m in missing:
        logger.warning("target %s not reachable; skipping", m)


def cmd_probe(cfg, args, logger):
    """Read-only reachability check: confirm the target resolves and show
    its top-level contents, so a full scan is never started blind."""
    roots = _resolve_roots(cfg, args, logger)
    rc = 0
    for root in roots:
        print(f"\nTarget: {root}")
        print(f"Report files will be named for: {drive_slug(root)}")
        if not os.path.isdir(root):
            print("  NOT REACHABLE")
            rc = 1
            continue
        try:
            with os.scandir(root) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            print(f"  reachable but cannot be listed: {exc}")
            rc = 1
            continue
        dirs, files, fbytes = [], 0, 0
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    dirs.append(e.name)
                elif e.is_file(follow_symlinks=False):
                    files += 1
                    fbytes += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass
        print(f"  REACHABLE - {len(dirs)} top-level folders, "
              f"{files} loose files ({fmt_gb(fbytes)})")
        for d in dirs:
            print(f"    [DIR]  {d}")
        if not dirs and not files:
            print("    (empty)")
    return rc


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
    _require_reachable(roots, logger)
    _verify_volume_identity(cfg, roots, logger)
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
    if args.refresh:
        for root in roots:
            prune_stale_hashes(cfg, root, logger)
    dref = _dref(cfg, logger)
    census = collect_size_census(cfg, roots, dref, logger)
    for root in roots:
        n = run_prefix_stage(cfg, root, census, dref, logger, args.max_files)
        print(f"{root}: prefix-hashed {n:,} candidate files")
    groups = collect_prefix_groups(cfg, roots)
    for root in roots:
        n = run_full_stage(cfg, root, groups, dref, logger, args.max_files)
        print(f"{root}: full-hashed {n:,} files")
    all_present = all(os.path.isdir(r) for r in roots)
    if args.max_files is None and all_present:
        write_hash_marker(cfg, roots)
    else:
        logger.warning("hash pass incomplete (%s) - completion marker "
                       "withheld; re-run `hash` to finish",
                       "max-files limit" if args.max_files is not None
                       else "a scan root was not attached")
    return 0


def _set_activity_cutoff(cfg):
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=int(cfg["active_project_days"]))
    cfg["_activity_cutoff_iso"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_classify(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    check_hash_marker(cfg, roots)
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


def _approved_scope(cfg):
    """Scan roots the user has approved, best effort - used to make sure a
    write target is not on one of them."""
    scope_path = os.path.join(cfg["output_dir"], "scope.json")
    if not os.path.exists(scope_path):
        return []
    try:
        return volumes_mod.load_approved_scope(scope_path)
    except SystemExit:
        raise
    except Exception:
        return []


def _resolve_workspace(cfg, args):
    """The folder holding every per-target run folder.

    Fully guarded, because both commands that take it WRITE inside it -
    crossdrive creates _cross-drive/, hashgaps appends to each run folder's
    hash CSVs. A lexical check alone is not enough (`E:\\x\\..` spells its way
    past one), so the workspace goes through the same guard as any other
    output directory: canonical path, volume identity against every approved
    scan root, and the Windows system-drive rule.
    """
    workspace = (args.workspace or os.path.dirname(
        cfg["output_dir"].rstrip("\\/")) or cfg["output_dir"]).strip().strip('"')
    if not os.path.isdir(workspace):
        raise SystemExit(f"workspace not found: {workspace}")
    probe = normalize_root(workspace)
    bare_share = is_unc(probe) and probe.strip("\\").count("\\") <= 1
    if re.fullmatch(r"[A-Za-z]:[\\/]?", probe) or bare_share:
        raise SystemExit(
            f"refusing {workspace} as the workspace: it is the root of a "
            f"whole drive or share, and this command writes into the "
            f"workspace. Point --workspace at the folder holding the "
            f"per-drive report folders (normally C:\\DEV\\triage).")
    guard_output_dirs({**cfg, "output_dir": workspace,
                       "scan_roots": _approved_scope(cfg)})
    return workspace


def cmd_crossdrive(cfg, args, logger):
    """Compare every completed run in the workspace against each other."""
    workspace = _resolve_workspace(cfg, args)
    logger.info("cross-drive analysis over %s", workspace)
    res = crossdrive.analyze(workspace, logger)
    print(f"\nCompared {len(res['runs'])} drives: {', '.join(res['runs'])}")
    print(f"{res['groups']:,} pieces of content exist on more than one drive")
    print(f"{fmt_gb(res['reclaimable'])} reclaimable by keeping one copy "
          f"of each")
    if res["gap_files"]:
        print(f"{res['gap_files']:,} files could not be compared "
              f"(never hashed) - see the report's Coverage section")
    if res.get("unexamined"):
        print(f"{res['unexamined']:,} inventory row(s) record something that "
              f"could NOT be read; their contents are in no comparison")
    print(f"\nwrote {res['report']}")
    print(f"wrote {res['groups_csv']}")
    return 0


def cmd_hashgaps(cfg, args, logger):
    """Hash only the files no run ever hashed, so crossdrive can see them."""
    workspace = _resolve_workspace(cfg, args)
    logger.info("closing the cross-drive coverage gap over %s", workspace)

    def echo(msg):
        # this pass can run for hours per drive, and the console handler only
        # shows warnings, so say out loud which drive is being read
        print(msg, flush=True)

    print(f"Detailed progress goes to {cfg['log_dir']}")
    res = hashgaps.run(workspace, logger, only=args.run or None, echo=echo)
    print(f"\nGap list: {res['gap_total']:,} files that no run had hashed")
    for line in hashgaps.format_summary(res):
        print(line)
    print(f"\n{res['full_hashed']:,} files newly full-hashed.")
    if res["full_hashed"]:
        print("Run Compare All Drives again to fold them into the "
              "comparison.")
    elif not res["processed"]:
        print("No drive could be verified, so nothing was hashed. Attach a "
              "drive that was scanned and run this again.")
    return 0


def cmd_all(cfg, args, logger):
    cmd_inventory(cfg, args, logger)
    cmd_hash(cfg, args, logger)
    cmd_classify(cfg, args, logger)
    cmd_report(cfg, args, logger)
    return 0


COMMANDS = {
    "enumerate": cmd_enumerate,
    "probe": cmd_probe,
    "inventory": cmd_inventory,
    "hash": cmd_hash,
    "classify": cmd_classify,
    "report": cmd_report,
    "crossdrive": cmd_crossdrive,
    "hashgaps": cmd_hashgaps,
    "all": cmd_all,
}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="triage",
        description=f"Read-only external drive triage v{__version__}")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--config", default="", help="path to triage-config.json")
    ap.add_argument("--drive", action="append", default=[],
                    help="scan target: drive letter (E, E:, E:\\) or UNC "
                         "share (\\\\server\\share). Repeatable; overrides "
                         "scope/config")
    ap.add_argument("--output-dir", default="", help="override output_dir")
    ap.add_argument("--log-dir", default="", help="override log_dir")
    ap.add_argument("--d-reference", default="",
                    help="override d_reference_csv")
    ap.add_argument("--max-files", type=int, default=None,
                    help="stop each stage after N new rows (testing/resume)")
    ap.add_argument("--refresh", action="store_true",
                    help="re-walk the target's file list from scratch so "
                         "DELETED files drop out; hashes already computed "
                         "are reused, so unchanged files are not re-read")
    ap.add_argument("--workspace", default="",
                    help="crossdrive/hashgaps: folder containing all run "
                         "folders (default: parent of output_dir)")
    ap.add_argument("--run", action="append", default=[],
                    help="hashgaps: limit to these run folder NAMES "
                         "(e.g. --run NAS_PHOTOS). Repeatable")
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
    cfg["_refresh"] = bool(args.refresh)

    # Guard BEFORE creating any directory or log file. For scanning commands
    # the roots are fully resolved (scope.json included) right here, so a
    # guard violation aborts before a single byte lands anywhere; `enumerate`
    # guards against an existing approved scope plus the Windows
    # system-drive rule for the output/log dirs themselves.
    if args.command in ("crossdrive", "hashgaps"):
        # operate on completed run folders, not a scan target;
        # the workspace itself is guarded by _resolve_workspace
        guard_output_dirs({**cfg, "scan_roots": []})
    elif args.command in ("enumerate", "probe"):
        scope_path = os.path.join(cfg["output_dir"], "scope.json")
        roots = []
        if os.path.exists(scope_path):
            try:
                roots = volumes_mod.load_approved_scope(scope_path)
            except SystemExit:
                raise
            except Exception:
                roots = []
        guard_output_dirs({**cfg, "scan_roots": roots})
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
