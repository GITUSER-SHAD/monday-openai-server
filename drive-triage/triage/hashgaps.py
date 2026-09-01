"""Targeted re-hash of the files the per-drive runs never hashed.

Each drive was triaged in its own run folder, so its candidate test ("does
this size occur more than once?") only ever saw that one drive. A file whose
size was unique on its own drive but has a byte-identical twin on another
drive was therefore never opened, and cross-drive comparison cannot see it.
`crossdrive` names exactly those files in cross-drive-gaps.csv; this module
hashes only them and appends the results into the same per-run CSVs the
normal stages write, so the next `crossdrive` run picks them up with no
re-scan of anything already done.

Read-only against scanned drives: files are opened "rb", and nothing is
written outside each run folder's own hashes/ directory.

The danger this module exists to defend against: several drives in this
fleet were all mounted as F:, so a path recorded by one run can resolve to a
DIFFERENT disk today. Hashing then records another drive's bytes under this
drive's paths, which fabricates a duplicate - the one error that could later
justify deleting the only copy of something. So a drive is hashed only while
it proves it is the drive that was scanned:

  * on Windows the volume label and size stamped beside the inventory when
    it was built must still match what is mounted at that letter;
  * a spread sample of files that run already hashed is re-read and the
    hashes must match - metadata alone is never enough, because a clone or a
    timestamp-preserving copy reproduces size and mtime exactly;
  * samples that are simply ABSENT are disqualifying too, not neutral. A
    sibling drive that happens to share a few paths (a partial backup of the
    same fleet) must not pass on the three files it does have;
  * the check is repeated immediately before the whole-file pass, which can
    start hours after the first one, because drives get swapped overnight;
  * every file is re-stat'd at full-hash time and skipped if its size or
    mtime moved since the prefix pass.

Convergence, for drives that cannot be attached at the same time: a file is
only worth a full hash once something else in the fleet shares its 64KB
prefix, so a twin pair split across two drives that both mount as F: needs
each drive attached twice. The summary says exactly which drives still owe a
full hash and how many files, so that is a stated next step, never a silent
omission.
"""

import errno
import os
import time
from collections import Counter, defaultdict

from .util import (
    HASH_COLUMNS, INVENTORY_COLUMNS, CsvAppender, extended_path, iso_utc,
    load_json, norm_key, read_csv_rows,
)
from .hashing import (
    _load_hashed, _same_identity, sha256_full, sha256_prefix,
)
from .inventory import _Muffled, _is_permission_error
from .crossdrive import CROSS_DIR, GAP_COLUMNS, find_runs
from . import volumes as volumes_mod

# How many already-hashed files to re-read to prove the right volume is
# mounted, and how much slack to allow. The sample must be almost entirely
# present AND matching: "present and identical" is the only evidence that
# counts, and a drive that is missing most of the sample is a different drive.
_VERIFY_SAMPLES = 8
_VERIFY_MIN_MATCHES = 3
_VERIFY_MAX_MISSING = 1

# Consecutive unreadable files that mean the device is gone rather than that
# these particular files are bad. Deleted files and permission denials never
# count: the gap list is a snapshot from the last comparison, so files that
# have since been removed are expected.
_MAX_CONSECUTIVE_FAILURES = 25


class DriveGone(Exception):
    """The device stopped responding part-way through. Resumable."""


class _GapBreaker:
    def __init__(self, name, stage):
        self.name, self.stage = name, stage
        self.consecutive = 0
        self.denied = self.vanished = self.errors = 0

    def success(self):
        self.consecutive = 0

    def gone(self):
        """A file that is simply not there any more - not a device fault."""
        self.vanished += 1
        self.consecutive = 0

    def failure(self, exc=None):
        if exc is not None and _is_permission_error(exc):
            self.denied += 1
            return
        self.errors += 1
        self.consecutive += 1
        if self.consecutive >= _MAX_CONSECUTIVE_FAILURES:
            raise DriveGone(
                f"{self.consecutive} consecutive read failures during "
                f"{self.stage}")


def _retrying_stat(path):
    """stat with the same backoff every other read in this tool uses -
    removable and SMB media hiccup, and one blip must not be read as a
    detached drive."""
    last = None
    for attempt in range(3):
        try:
            return os.stat(extended_path(path))
        except OSError as exc:
            last = exc
            if exc.errno == errno.ENOENT or attempt == 2:
                break
            time.sleep(0.5 * (attempt + 1))
    raise last


def gaps_csv_path(workspace):
    return os.path.join(workspace, CROSS_DIR, "manifests",
                        "cross-drive-gaps.csv")


def load_gaps(workspace, logger):
    """drive name -> [path, ...] from the coverage gap list crossdrive wrote."""
    csv_path = gaps_csv_path(workspace)
    if not os.path.exists(csv_path):
        raise SystemExit(
            f"no gap list at {csv_path}. Run the cross-drive comparison "
            f"first (Compare All Drives.bat); it writes the list of files "
            f"that could not be compared.")
    by_drive = defaultdict(list)
    for row in read_csv_rows(csv_path, GAP_COLUMNS):
        if row["drive"] and row["path"]:
            by_drive[row["drive"]].append(row["path"])
    logger.info("gap list: %d files across %d drives",
                sum(len(v) for v in by_drive.values()), len(by_drive))
    return by_drive


def _csvs_in(run_dir, sub, prefix):
    d = os.path.join(run_dir, sub)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.startswith(prefix) and f.endswith(".csv")]


def run_slugs(run_dir):
    """Every per-target slug this run folder holds.

    Usually one. A folder built from more than one target holds several, and
    they must be kept apart: each names a DIFFERENT physical volume, so
    proving one is mounted says nothing about the others.
    """
    slugs = set()
    for sub, prefix in (("inventory", "inventory-"), ("hashes", "prefix-")):
        for path in _csvs_in(run_dir, sub, prefix):
            base = os.path.basename(path)
            slugs.add(base[len(prefix):-len(".csv")])
    return sorted(slugs)


def hash_csvs(run_dir, slug):
    base = os.path.join(run_dir, "hashes")
    return (os.path.join(base, f"prefix-{slug}.csv"),
            os.path.join(base, f"full-{slug}.csv"))


def split_by_slug(run_dir, slugs, paths, logger):
    """Route each gap path to the slug (volume) whose inventory recorded it.

    With one slug this is free. With several it is the difference between
    verifying volume E: and then hashing F:'s files off whatever is mounted.
    """
    if len(slugs) == 1:
        return {slugs[0]: list(paths)}
    wanted = {norm_key(p): p for p in paths}
    out = defaultdict(list)
    for slug in slugs:
        inv = os.path.join(run_dir, "inventory", f"inventory-{slug}.csv")
        if not os.path.exists(inv):
            continue
        for row in read_csv_rows(inv, INVENTORY_COLUMNS):
            key = norm_key(row["path"])
            if key in wanted:
                out[slug].append(wanted.pop(key))
    if wanted:
        logger.warning("%s: %d gap path(s) match no inventory in this run "
                       "folder and are left alone",
                       os.path.basename(run_dir), len(wanted))
    return out


def _spread(items, n):
    """Up to n items spread evenly across the sequence, not just the head -
    a wrong volume can easily share a first directory."""
    if len(items) <= n:
        return list(items)
    step = len(items) / float(n)
    return [items[int(i * step)] for i in range(n)]


def recorded_volume_mismatch(run_dir, slug, signatures):
    """Reason string when Windows says a different volume is at this letter.

    `inventory` stamps the volume label+size beside each inventory as
    inventory-<slug>.meta.json. When that stamp exists and disagrees with
    what is mounted now, no amount of sampled content matters: it is a
    different disk, and saying so by name beats inferring it from files.
    """
    if not signatures:
        return None
    prev = load_json(os.path.join(run_dir, "inventory",
                                  f"inventory-{slug}.meta.json"))
    if not prev:
        return None
    now = signatures.get(f"{slug.upper()}:")
    if not now:
        return None
    if (prev.get("label"), prev.get("size")) != (now.get("label"),
                                                 now.get("size")):
        return (f"a different volume is mounted here: this run recorded "
                f"{prev.get('label')!r} ({prev.get('size')} bytes), the "
                f"drive present now is {now.get('label')!r} "
                f"({now.get('size')} bytes)")
    return None


def verify_volume(run_dir, slug, logger, quiet=False, signatures=None):
    """Prove the volume currently at this run's paths is the one it scanned.

    Returns (ok, reason). Content only: a spread sample of files this run
    already prefix-hashed is re-read and the hashes must match. A run with
    too few hashed files to sample is refused rather than trusted - it also
    has almost nothing to gain, since a drive with no hashes had no
    size collisions to begin with.
    """
    mismatch = recorded_volume_mismatch(run_dir, slug, signatures)
    if mismatch:
        return False, mismatch
    prefix_csv, _ = hash_csvs(run_dir, slug)
    rows = []
    if os.path.exists(prefix_csv):
        rows = [r for r in _load_hashed(prefix_csv).values()
                if r["prefix_sha256"] and not r["error"] and r["size"]]
    if len(rows) < _VERIFY_MIN_MATCHES:
        return False, (
            f"cannot be verified: this run recorded only {len(rows)} hashed "
            f"file(s), too few to prove the right disk is mounted")

    sample = _spread(sorted(rows, key=lambda r: r["path"]), _VERIFY_SAMPLES)
    matched = mismatched = missing = 0
    for row in sample:
        path = row["path"]
        try:
            st = _retrying_stat(path)
        except OSError:
            missing += 1
            continue
        if str(st.st_size) != str(row["size"]):
            mismatched += 1
            continue
        try:
            pre, _ = sha256_prefix(path)
        except OSError:
            missing += 1
            continue
        if pre == row["prefix_sha256"]:
            matched += 1
        else:
            mismatched += 1

    n = len(sample)
    if mismatched:
        return False, (
            f"DIFFERENT CONTENT at this run's paths ({mismatched} of {n} "
            f"sample files differ) - another drive is mounted where this one "
            f"was, or its files changed")
    if missing > _VERIFY_MAX_MISSING:
        return False, (
            f"not the drive that was scanned, or not attached: only "
            f"{matched} of {n} sample files are present")
    if matched < _VERIFY_MIN_MATCHES:
        return False, (f"only {matched} of {n} sample files could be read - "
                       f"too little evidence to hash this drive")
    if not quiet:
        logger.info("%s [%s]: volume confirmed - %d/%d sampled files "
                    "re-read and identical", os.path.basename(run_dir), slug,
                    matched, n)
    return True, ""


def _prefix_gaps(run_dir, slug, paths, logger, breaker):
    """Prefix-hash this volume's gap files. Returns (written, errors)."""
    prefix_csv, _ = hash_csvs(run_dir, slug)
    done = _load_hashed(prefix_csv)
    err_log = _Muffled(logger)
    written = 0
    label = f"{os.path.basename(run_dir)} [{slug}]"
    with CsvAppender(prefix_csv, HASH_COLUMNS, flush_every=200) as out:
        for path in paths:
            try:
                st = _retrying_stat(path)
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.ENOENT:
                    breaker.gone()   # deleted since the comparison: expected
                else:
                    err_log.warn("gap file unreadable: %s: %s", path, exc)
                    breaker.failure(exc)
                continue
            breaker.success()
            if st.st_size == 0:
                continue  # zero-byte: junk by size, never hashed
            mtime = iso_utc(st.st_mtime)
            if _same_identity(done.get(norm_key(path)), str(st.st_size),
                              mtime):
                continue
            rec = {"path": path, "size": str(st.st_size),
                   "modified_utc": mtime, "prefix_sha256": "",
                   "full_sha256": "", "error": ""}
            try:
                pre, full = sha256_prefix(path)
                rec["prefix_sha256"] = pre
                rec["full_sha256"] = full or ""
                breaker.success()
                written += 1
            except OSError as exc:
                rec["error"] = str(exc)
                err_log.warn("prefix hash failed for %s: %s", path, exc)
                breaker.failure(exc)
            out.write(rec)
            if written and written % 2000 == 0:
                logger.info("%s: prefix-hashed %d gap files", label, written)
    return written


def global_prefix_groups(runs, logger):
    """(size, prefix_sha256) -> count, across EVERY run in the workspace.

    This is the whole point of the command: each per-drive run grouped only
    within itself, which is what created the gap. Counting across all drives
    at once is what lets a size-unique file find its twin.
    """
    groups = Counter()
    for _name, run_dir in runs:
        for slug in run_slugs(run_dir):
            prefix_csv, _ = hash_csvs(run_dir, slug)
            if not os.path.exists(prefix_csv):
                continue
            for row in _load_hashed(prefix_csv).values():
                if row["error"] or not row["prefix_sha256"] or not row["size"]:
                    continue
                groups[(int(row["size"]), row["prefix_sha256"])] += 1
    logger.info("global prefix census: %d distinct (size, prefix) groups",
                len(groups))
    return groups


def _needs_full(run_dir, slug, paths, groups):
    """Gap rows on this volume that a full hash would now decide.

    A prefix group of one proves no byte-identical twin exists anywhere in
    the fleet, so those files are finished without ever being read whole.
    """
    prefix_csv, full_csv = hash_csvs(run_dir, slug)
    if not os.path.exists(prefix_csv):
        return []
    wanted = {norm_key(p) for p in paths}
    done = _load_hashed(full_csv)
    out = []
    for key, row in _load_hashed(prefix_csv).items():
        if key not in wanted or row["error"] or not row["prefix_sha256"]:
            continue
        if row["full_sha256"]:
            continue  # small file: the prefix hash IS the full hash
        if not row["size"] or groups[(int(row["size"]),
                                      row["prefix_sha256"])] < 2:
            continue
        if _same_identity(done.get(key), row["size"], row["modified_utc"]):
            continue
        out.append(row)
    return out


def _full_gaps(run_dir, slug, rows, logger, breaker):
    """Full-hash the rows _needs_full selected. Returns rows written.

    Each file is re-stat'd first: this pass can begin hours after the prefix
    pass, and a size or mtime that moved means the recorded prefix no longer
    describes the bytes about to be read. Those are left for the next run's
    prefix pass rather than recorded against stale metadata.
    """
    _prefix_csv, full_csv = hash_csvs(run_dir, slug)
    err_log = _Muffled(logger)
    written = 0
    label = f"{os.path.basename(run_dir)} [{slug}]"
    with CsvAppender(full_csv, HASH_COLUMNS, flush_every=50) as out:
        for row in rows:
            path = row["path"]
            try:
                st = _retrying_stat(path)
            except OSError as exc:
                if getattr(exc, "errno", None) == errno.ENOENT:
                    breaker.gone()
                else:
                    err_log.warn("full hash skipped, unreadable: %s: %s",
                                 path, exc)
                    breaker.failure(exc)
                continue
            breaker.success()
            if (str(st.st_size) != str(row["size"]) or
                    iso_utc(st.st_mtime) != row["modified_utc"]):
                err_log.warn("changed since it was prefix-hashed, left for "
                             "the next run: %s", path)
                continue
            rec = dict(row)
            rec["error"] = ""
            try:
                rec["full_sha256"] = sha256_full(path)
                breaker.success()
                written += 1
            except OSError as exc:
                rec["full_sha256"] = ""
                rec["error"] = str(exc)
                err_log.warn("full hash failed for %s: %s", path, exc)
                breaker.failure(exc)
            out.write(rec)
            if written <= 5 or written % 25 == 0:
                logger.info("%s: full-hashed %d gap files", label, written)
    return written


def _plan(workspace, by_drive, only, logger):
    """[(drive, run_dir, slug, [gap paths])], skipping what cannot be done."""
    known = {n for n, _ in find_runs(workspace)}
    plan, skipped = [], []
    for name in sorted(by_drive):
        if only and name.casefold() not in only:
            continue
        if name not in known:
            skipped.append((name, "no run folder by this name in the "
                                  "workspace (renamed, moved, or its "
                                  "inventory folder is missing)"))
    for name, run_dir in find_runs(workspace):
        if name not in by_drive:
            continue
        if only and name.casefold() not in only:
            continue
        slugs = run_slugs(run_dir)
        if not slugs:
            skipped.append((name, "no inventory or hash CSV in this folder"))
            continue
        for slug, paths in split_by_slug(run_dir, slugs, by_drive[name],
                                         logger).items():
            if paths:
                plan.append((name, run_dir, slug, paths))
    return plan, skipped


def run(workspace, logger, only=None, echo=None):
    """Close the cross-drive coverage gap. Returns a summary dict.

    Volumes are handled independently and every stage is resumable, so a
    fleet of externals that share drive letters is worked through one
    attachment at a time: run it, swap the drive, run it again.
    """
    say = echo or (lambda _msg: None)
    only = {o.casefold() for o in only} if only else None
    signatures = volumes_mod.volume_signatures(logger)
    by_drive = load_gaps(workspace, logger)
    plan, skipped = _plan(workspace, by_drive, only, logger)
    if only and not plan:
        raise SystemExit(
            f"no run folder in {workspace} with gap files matches "
            f"{', '.join(sorted(only))}")

    # ---- pass 1: prefix-hash the gap files on every verified volume ------
    verified = []
    errors = 0
    for name, run_dir, slug, paths in plan:
        label = name if len(run_slugs(run_dir)) == 1 else f"{name} [{slug}]"
        ok, why = verify_volume(run_dir, slug, logger,
                                signatures=signatures)
        if not ok:
            logger.warning("SKIPPING %s: %s", label, why)
            skipped.append((label, why))
            continue
        say(f"  {label}: reading {len(paths):,} gap files...")
        breaker = _GapBreaker(label, "prefix hashing")
        try:
            n = _prefix_gaps(run_dir, slug, paths, logger, breaker)
        except DriveGone as exc:
            logger.warning("%s: %s", label, exc)
            skipped.append((label, "stopped responding part-way through; "
                                   "re-run with it attached to finish"))
            continue
        errors += breaker.errors + breaker.denied
        if breaker.denied or breaker.errors:
            logger.warning("%s: %d permission-denied, %d unreadable during "
                           "prefix hashing", label, breaker.denied,
                           breaker.errors)
        logger.info("%s: prefix-hashed %d of %d gap files", label, n,
                    len(paths))
        verified.append((name, label, run_dir, slug, paths))

    # ---- the census only means anything once every reachable volume has
    # contributed its prefixes, so it happens between the two passes -------
    groups = global_prefix_groups(list(find_runs(workspace)), logger)

    # ---- pass 2: full-hash only where the census says it decides ---------
    processed, full_total = [], 0
    for name, label, run_dir, slug, paths in verified:
        rows = _needs_full(run_dir, slug, paths, groups)
        if not rows:
            processed.append((label, len(paths), 0))
            continue
        # hours may have passed and drives get swapped: prove it again
        ok, why = verify_volume(run_dir, slug, logger, quiet=True,
                                signatures=signatures)
        if not ok:
            logger.warning("%s: volume changed since the first pass: %s",
                           label, why)
            skipped.append((label, f"volume changed mid-run ({why}); its "
                                   f"whole-file hashes were not taken"))
            continue
        say(f"  {label}: full-hashing {len(rows):,} files...")
        breaker = _GapBreaker(label, "full hashing")
        try:
            n = _full_gaps(run_dir, slug, rows, logger, breaker)
        except DriveGone as exc:
            logger.warning("%s: %s", label, exc)
            skipped.append((label, "stopped responding during whole-file "
                                   "hashing; re-run with it attached"))
            continue
        errors += breaker.errors + breaker.denied
        full_total += n
        processed.append((label, len(paths), n))

    # ---- what still owes a full hash ------------------------------------
    # A file whose prefix now matches something on another drive is a
    # probable duplicate that only a whole-file read can confirm. When its
    # drive is not the one currently attached, that read has to wait - which
    # is a named next step here, never a silent omission.
    pending = []
    for name, run_dir in find_runs(workspace):
        if name not in by_drive:
            continue
        slugs = run_slugs(run_dir)
        for slug in slugs:
            outstanding = len(_needs_full(run_dir, slug, by_drive[name],
                                          groups))
            if outstanding:
                label = name if len(slugs) == 1 else f"{name} [{slug}]"
                pending.append((label, outstanding))

    return {
        "processed": processed,
        "skipped": skipped,
        "pending": pending,
        "full_hashed": full_total,
        "errors": errors,
        "gap_total": sum(len(v) for v in by_drive.values()),
    }


def format_summary(res):
    """Console lines: what was closed, what still needs a drive attached."""
    lines = []
    for label, gaps, hashed in res["processed"]:
        lines.append(f"  {label}: {gaps:,} gap files, {hashed:,} newly "
                     f"full-hashed")
    if res["errors"]:
        lines.append("")
        lines.append(f"  {res['errors']:,} file(s) could not be read and were "
                     f"recorded with an error, not as hashes.")
    if res["pending"]:
        lines.append("")
        lines.append("Matched against another drive but still needing a "
                     "whole-file hash:")
        for label, n in res["pending"]:
            lines.append(f"  {label}: {n:,} files")
        lines.append("  (attach those drives and run this again - drives "
                     "that share a letter need a second turn)")
    if res["skipped"]:
        lines.append("")
        lines.append("NOT DONE - these were left untouched:")
        for label, why in res["skipped"]:
            lines.append(f"  {label}: {why}")
    return lines
