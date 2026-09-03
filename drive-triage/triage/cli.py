"""Command-line entry point.

  python -m triage enumerate  [--config triage-config.json]
  python -m triage probe      --drive \\\\server\\share   (reachability check)
  python -m triage inventory  [--drive E:\\ | --drive \\\\server\\share] ...
  python -m triage hash
  python -m triage classify
  python -m triage reclassify [--workspace C:\\DEV\\triage] [--run NAME]
  python -m triage report
  python -m triage all        (inventory -> hash -> classify -> report)
  python -m triage crossdrive [--workspace C:\\DEV\\triage]
  python -m triage hashgaps   [--workspace C:\\DEV\\triage] [--run NAME]
  python -m triage plan       [--workspace C:\\DEV\\triage]

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
    INVENTORY_COLUMNS, IS_WINDOWS, atomic_write_json, drive_slug, fmt_gb,
    guard_output_dirs, is_unc, is_under, load_config, load_json,
    normalize_root, read_csv_rows, setup_logging,
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
from . import plan as plan_mod


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


def _run_info_path(cfg):
    return os.path.join(cfg["output_dir"], "run-info.json")


def _shared_cutoff_path(cfg):
    """Where the ONE activity cutoff for the whole fleet lives.

    Each target is triaged into its own output folder, so a per-folder
    cutoff would give every drive a different one - whichever day it
    happened to be scanned - and the fastwork/hdd-mirror line would move
    from drive to drive. The cutoff belongs to the workspace that holds all
    the run folders, so every drive is measured against the same date.
    """
    parent = os.path.dirname(cfg["output_dir"].rstrip("\\/"))
    return os.path.join(parent or cfg["output_dir"], "activity-cutoff.json")


def _set_activity_cutoff(cfg, args, logger):
    """Fix the activity cutoff for this run - and KEEP it fixed.

    The fastwork / hdd-mirror split hangs on this one date, and it used to
    be recomputed from the clock on every classify, so merely re-running
    months later silently moved projects between tiers and changed the NAS
    sizing with no record of why. Now: the first classify computes it,
    records it in run-info.json, and every later classify reuses the
    recorded date - identical inputs give identical classification. It only
    changes when the user says so (--cutoff).
    """
    if getattr(args, "cutoff", ""):
        try:
            datetime.strptime(args.cutoff, "%Y-%m-%d")
        except ValueError:
            raise SystemExit(
                f"--cutoff must be a real date as YYYY-MM-DD, got "
                f"{args.cutoff!r}")
        cfg["_activity_cutoff_iso"] = args.cutoff + "T00:00:00Z"
        source = "set by --cutoff"
    else:
        recorded = (load_json(_shared_cutoff_path(cfg)) or {}).get(
            "activity_cutoff_iso") or \
            (load_json(_run_info_path(cfg)) or {}).get("activity_cutoff_iso")
        if recorded:
            cfg["_activity_cutoff_iso"] = recorded
            source = "recorded by an earlier classify run (use --cutoff to " \
                     "change it for every drive)"
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=int(cfg["active_project_days"]))
            cfg["_activity_cutoff_iso"] = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
            source = f"today minus active_project_days=" \
                     f"{cfg['active_project_days']} - recorded now, so every "\
                     f"other drive is measured against this same date"
    logger.info("activity cutoff %s (%s)", cfg["_activity_cutoff_iso"],
                source)
    try:
        atomic_write_json(_shared_cutoff_path(cfg), {
            "activity_cutoff_iso": cfg["_activity_cutoff_iso"],
            "active_project_days": cfg["active_project_days"]})
    except OSError as exc:   # a read-only or absent parent must not abort
        logger.warning("could not record the shared activity cutoff (%s); "
                       "this drive still uses %s", exc,
                       cfg["_activity_cutoff_iso"])


def _write_run_info(cfg, args, roots):
    """The provenance record every output in this run folder belongs to."""
    atomic_write_json(_run_info_path(cfg), {
        "tool_version": __version__,
        "activity_cutoff_iso": cfg["_activity_cutoff_iso"],
        "active_project_days": cfg["active_project_days"],
        "config": args.config or "(built-in defaults)",
        "d_reference_csv": cfg["d_reference_csv"] or "(none)",
        "scan_roots": list(roots),
        "classified_at_utc": datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def cmd_classify(cfg, args, logger):
    roots = _resolve_roots(cfg, args, logger)
    check_hash_marker(cfg, roots)
    _set_activity_cutoff(cfg, args, logger)
    dref = _dref(cfg, logger)
    stats = run_classify(cfg, roots, dref, logger)
    _write_run_info(cfg, args, roots)
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


def _candidate_roots(path):
    r"""Every prefix of a recorded absolute path that could be its scan root,
    SHALLOWEST first.

    A drive letter or UNC share has exactly one answer ('F:\Foo\a' -> 'F:\',
    r'\\host\share\a' -> r'\\host\share') - neither can be scanned above
    itself. Anything else is walked up to the filesystem root and returned
    outermost-first, because two nested directories can share a basename and
    therefore a slug, and the outer one is the safer reading: it still
    contains every recorded row.
    """
    p = path.strip().strip('"')
    win = p.replace("/", "\\")
    if is_unc(win):
        parts = [q for q in win.lstrip("\\").split("\\") if q]
        if len(parts) >= 2:
            yield "\\\\" + parts[0] + "\\" + parts[1]
        return
    if re.match(r"^[A-Za-z]:[\\]", win):
        yield win[0].upper() + ":\\"
        return
    up, cur = [], os.path.dirname(p)
    while cur and cur != os.path.dirname(cur):
        up.append(cur)
        cur = os.path.dirname(cur)
    for root in reversed(up):
        yield root


def _root_of_run(run_dir, slug):
    """Recover the scan root a run folder's inventory was built from.

    Returns (root, status): ("F:\\", "ok"), (None, "empty") for a folder
    whose drive genuinely held no files, or (None, reason) when it cannot be
    established.

    Nothing outside the run folder records the root: eight of this fleet's
    targets were all mounted at F:\\, so the letter identifies nothing, and
    the folder name is free text. Three sources are tried, strongest first:

    1. run-info.json, written by classify itself - authoritative when present.
    2. Otherwise the paths the inventory recorded. `drive_slug` is not
       injective (nested folders sharing a basename slug alike), so a slug
       match alone can be satisfied by the wrong prefix. The candidate must
       also sit at or above the deepest directory common to EVERY recorded
       row, which rules the too-deep readings out.
    3. Whatever survives is then checked against every recorded row: one row
       outside it means the wrong root, and it refuses.

    A scan root deeper than a drive letter or a UNC share cannot be told
    apart from its drive or share by paths alone, so it is recovered as the
    drive or share. This fleet has no such root, and once a folder carries a
    run-info.json the question does not arise again.
    """
    csv_path = os.path.join(run_dir, "inventory", f"inventory-{slug}.csv")
    if not os.path.exists(csv_path):
        return None, f"no inventory-{slug}.csv in this folder"

    paths = [(r["path"] or "").strip()
             for r in read_csv_rows(csv_path, INVENTORY_COLUMNS)
             if (r["path"] or "").strip()]
    if not paths:
        return None, "empty"

    recorded = (load_json(os.path.join(run_dir, "run-info.json")) or {}).get(
        "scan_roots") or []
    for root in recorded:
        if drive_slug(root) == slug and _covers(root, paths):
            return root, "ok"

    common = _common_dir(paths)
    for root in _candidate_roots(paths[0]):
        if drive_slug(root) != slug:
            continue
        if not (is_under(common, root) or _same_path(common, root)):
            continue          # a reading deeper than the rows allow
        if not _covers(root, paths):
            break             # rows outside it: this folder mixes drives
        return root, "ok"
    return None, ("its recorded paths do not agree on a scan root that "
                  f"matches '{slug}'")


def _same_path(a, b):
    n = (lambda s: s.rstrip("\\/").casefold() if IS_WINDOWS
         else s.rstrip("/"))
    return n(a) == n(b)


def _covers(root, paths):
    return all(is_under(p, root) for p in paths)


def _common_dir(paths):
    """Deepest directory containing every recorded path."""
    sep = "\\" if any("\\" in p for p in paths) else "/"
    split = [p.replace("/", sep).split(sep) for p in paths]
    common = split[0][:-1]
    for parts in split[1:]:
        keep = 0
        for a, b in zip(common, parts[:-1]):
            same = a.casefold() == b.casefold() if IS_WINDOWS else a == b
            if not same:
                break
            keep += 1
        common = common[:keep]
    return sep.join(common) or sep


def cmd_reclassify(cfg, args, logger):
    """Re-run classify and report over every run folder in the workspace.

    Classification reads only the recorded CSVs, so no drive is touched and
    nothing needs to be plugged in. This exists because per-drive classify
    output goes stale in two ways the user cannot see: whole-file hashes
    added later (hashgaps) prove duplicates the earlier run had to call
    unique, and a change to the rules moves the ground under every drive
    already classified. Re-running one drive at a time would also give each
    a different activity cutoff; here they all share the recorded one.
    """
    workspace = _resolve_workspace(cfg, args)
    only = {o.casefold() for o in args.run} if args.run else None
    runs = [(n, d) for n, d in crossdrive.find_runs(workspace)
            if not only or n.casefold() in only]
    skipped = []
    if only:
        for want in args.run:                 # echoed as the user typed it
            if not any(n.casefold() == want.casefold() for n, _ in runs):
                skipped.append((want, "no run folder by this name in "
                                      f"{workspace}"))
    if not runs:
        print(f"No run folder to re-classify in {workspace}.")
        print("A run folder is a subfolder holding an 'inventory' directory. "
              "If this is the wrong place, point --workspace at the folder "
              "that holds the per-drive folders (normally C:\\DEV\\triage).")
        for name, why in skipped:
            print(f"  {name}: {why}")
        return 1

    # Settled ONCE, then forced on every folder: the per-folder call records
    # to a shared file, but that write is allowed to fail (a read-only parent
    # only warns), and two folders computing "today minus
    # active_project_days" independently is exactly the drift this command
    # exists to remove.
    seed = {**cfg, "output_dir": runs[0][1]}
    _set_activity_cutoff(seed, args, logger)
    cutoff = seed["_activity_cutoff_iso"]
    if not args.cutoff:
        # With no shared file yet, the seed fell back to one folder's own
        # run-info.json. Say so when the others disagree, instead of moving
        # a drive between tiers on the strength of alphabetical order.
        others = sorted({
            (load_json(os.path.join(d, "run-info.json")) or {}).get(
                "activity_cutoff_iso")
            for _n, d in runs} - {None, "", cutoff})
        if others:
            print(f"Note: these folders were last classified against "
                  f"{', '.join(others)}; all of them now move to {cutoff}. "
                  f"Pass --cutoff YYYY-MM-DD to choose a different date for "
                  f"the whole fleet.")

    done, empty = [], []
    for name, run_dir in runs:
        slugs = hashgaps.run_slugs(run_dir)
        if not slugs:
            skipped.append((name, "no inventory or hash CSV in this folder"))
            continue
        roots, blank, unknown = [], [], []
        for slug in slugs:
            root, why = _root_of_run(run_dir, slug)
            if root:
                roots.append(root)
            elif why == "empty":
                blank.append(slug)
            else:
                unknown.append(f"{slug}: {why}")
        # A folder is re-classified whole or not at all. Doing the slugs that
        # resolved would leave the rest silently stale behind a rewritten
        # run-info.json claiming the folder was done.
        if unknown:
            why = "cannot recover the scan root for " + "; ".join(unknown)
            if roots or blank:
                why += (f" - the other {len(roots) + len(blank)} drive(s) in "
                        f"this folder were left alone too, so nothing here "
                        f"is half-updated")
            skipped.append((name, why))
            continue
        if not roots:
            empty.append(name)          # every drive here held no files
            continue
        run_cfg = {**cfg, "output_dir": run_dir, "scan_roots": list(roots),
                   "_activity_cutoff_iso": cutoff}
        # Both the roots this folder came from and any approved scope: the
        # guard must know every drive it is forbidden to write onto, and
        # scope.json is frequently absent when targets were passed as --drive.
        guard_output_dirs({**run_cfg,
                           "scan_roots": list(roots) + _approved_scope(cfg)})
        try:
            check_hash_marker(run_cfg, roots)
            print(f"\n{name}: {', '.join(roots)}")
            # Reloaded per run: run_classify drops D-reference entries that
            # sit under the roots it is given, in place. Sharing one object
            # across the fleet would shrink the reference drive by drive, so
            # every run after the first is classified against a different D.
            stats = run_classify(run_cfg, roots, _dref(cfg, logger), logger)
            _write_run_info(run_cfg, args, roots)
        except SystemExit as exc:
            # One bad folder must not abandon the fourteen behind it, and
            # must never take the summary down with it: that is what tells
            # the user the fleet is now half old and half new.
            logger.warning("%s: %s", name, exc)
            skipped.append((name, " ".join(str(exc).split())))
            continue
        for root, counts in sorted(stats.items()):
            print(f"  {root}: " + ", ".join(
                f"{k}={v:,}" for k, v in sorted(counts.items())))
        try:
            for out in run_reports(run_cfg, roots, logger):
                print(f"  wrote {out}")
        except SystemExit as exc:
            logger.warning("%s: reports: %s", name, exc)
            skipped.append((name, "classified, but its reports could not be "
                                  f"written: {' '.join(str(exc).split())}"))
            continue
        done.append(name)

    print(f"\nRe-classified {len(done)} run folder(s) against cutoff "
          f"{cutoff}.")
    if empty:
        print(f"Nothing to classify in {len(empty)}: "
              f"{', '.join(sorted(empty))} (those drives held no files).")
    if skipped:
        print("\nNOT re-classified:")
        for name, why in skipped:
            print(f"  {name}: {why}")
        print("\nThose folders keep their PREVIOUS classification. A plan "
              "built now would mix old answers with new ones, so sort these "
              "out (or move them out of the workspace) and run this again.")
        return 1
    if only:
        print(f"\nOnly the folder(s) named with --run were touched; the rest "
              f"of {workspace} still holds its previous classification. Do "
              f"not build the plan until every folder has been re-classified "
              f"against this cutoff.")
        return 1
    print("Every run folder is now classified by the same rules and the "
          "same cutoff. Next: Build the Plan.")
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


def cmd_plan(cfg, args, logger):
    """One verified, ordered, collision-free plan over every classified run."""
    workspace = _resolve_workspace(cfg, args)
    logger.info("building execution plan over %s", workspace)
    res = plan_mod.build(workspace, logger)
    print(f"\nPLAN WRITTEN - nothing was executed.")
    print(f"  {res['copies']:,} copies ({fmt_gb(res['copy_bytes'])}), "
          f"{res['deletes']:,} delete-candidates "
          f"({fmt_gb(res['delete_bytes'])})")
    print(f"  {res['merged']:,} identical sources merged, "
          f"{res['qualified']:,} destinations qualified by source drive")
    print(f"  HELD OUT: {res['held']:,} undecided rows (decision list), "
          f"{res['held_deletes']:,} deletes that could not be proven "
          f"({fmt_gb(res['held_delete_bytes'])}) - see the report")
    print(f"\nwrote {res['plan_csv']}")
    print(f"wrote {res['report']}")
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
    "reclassify": cmd_reclassify,
    "report": cmd_report,
    "crossdrive": cmd_crossdrive,
    "hashgaps": cmd_hashgaps,
    "plan": cmd_plan,
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
    ap.add_argument("--cutoff", default="",
                    help="classify: freeze the fastwork-activity cutoff to "
                         "this date (YYYY-MM-DD) and record it; otherwise "
                         "the date recorded by the previous classify run is "
                         "reused")
    ap.add_argument("--refresh", action="store_true",
                    help="re-walk the target's file list from scratch so "
                         "DELETED files drop out; hashes already computed "
                         "are reused, so unchanged files are not re-read")
    ap.add_argument("--workspace", default="",
                    help="crossdrive/hashgaps: folder containing all run "
                         "folders (default: parent of output_dir)")
    ap.add_argument("--run", action="append", default=[],
                    help="hashgaps/reclassify: limit to these run folder "
                         "NAMES (e.g. --run NAS_PHOTOS). Repeatable")
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
    if args.command in ("crossdrive", "hashgaps", "plan", "reclassify"):
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
