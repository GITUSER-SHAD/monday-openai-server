"""Phase 1b: two-stage duplicate hashing. Read-only, resumable per drive.

Stage 1 (cheap): a file is a *candidate* only if its size occurs more than
once across (all external inventories + the D: reference set). Candidates get
a SHA256 of their first 64KB ("prefix hash").

Stage 2 (expensive): full SHA256 only where it can decide something -
  * the (size, prefix) group has >= 2 external members, or
  * the size matches a D: reference entry carrying a full SHA256 (and, when
    the reference also carries prefix hashes, only if the prefix matches too).
Files <= 64KB are finished in stage 1 (prefix hash IS the full hash).

Resume model: per-drive append-only CSVs (prefix-<slug>.csv, full-<slug>.csv);
on restart, already-hashed paths (matching size+mtime) are skipped. There is
no per-stage short-circuit marker: re-running always re-streams the
inventories and hashes whatever is missing, so adding a drive later simply
extends the candidate set convergently. Completion for the downstream gate is
recorded as a fingerprint of the inventories the hash pass covered
(hash.done); classify refuses to run when the fingerprint is stale.

A circuit breaker aborts a stage (resumably) after many consecutive open
failures - a detached drive must fail in seconds, not grind through retry
backoffs for every remaining file.
"""

import hashlib
import os
import time
from collections import Counter

from .util import (
    HASH_COLUMNS, PREFIX_BYTES, CsvAppender, atomic_write_json, drive_slug,
    extended_path, load_json, norm_key, read_csv_rows,
)
from .inventory import (
    _Muffled, _is_permission_error, inventory_paths, iter_inventory,
)

_READ_CHUNK = 1024 * 1024
_MAX_CONSECUTIVE_FAILURES = 25


def hash_paths(cfg, root):
    slug = drive_slug(root)
    base = os.path.join(cfg["output_dir"], "hashes")
    return {
        "prefix": os.path.join(base, f"prefix-{slug}.csv"),
        "full": os.path.join(base, f"full-{slug}.csv"),
        "slug": slug,
    }


def _retrying_open(path):
    last = None
    for attempt in range(3):
        try:
            return open(extended_path(path), "rb")
        except OSError as exc:
            last = exc
            time.sleep(0.5 * (attempt + 1))  # removable-media hiccup backoff
    raise last


class _CircuitBreaker:
    """Abort (resumably) when every recent file open fails - the drive is
    gone; per-file retry backoff would otherwise take days on a big drive.

    Permission denials never count: files locked to SYSTEM (Windows crypto
    MachineKeys, service state) are permanently unreadable by design and
    can appear in long consecutive runs, which is not a failing drive.
    """

    def __init__(self, root, stage):
        self.root, self.stage, self.consecutive, self.denied = root, stage, 0, 0

    def success(self):
        self.consecutive = 0

    def failure(self, exc=None):
        if exc is not None and _is_permission_error(exc):
            self.denied += 1
            return
        self.consecutive += 1
        if self.consecutive >= _MAX_CONSECUTIVE_FAILURES:
            raise SystemExit(
                f"{self.stage} stage on {self.root}: "
                f"{self.consecutive} consecutive read failures - drive "
                f"detached or unreadable. State is resumable; re-run `hash` "
                f"when the drive is healthy.")


def sha256_prefix(path):
    """Return (prefix_sha256, full_sha256_or_None). Full is set when the file
    fits within PREFIX_BYTES, i.e. the prefix hash is the full hash."""
    h = hashlib.sha256()
    with _retrying_open(path) as fh:
        data = fh.read(PREFIX_BYTES)
        h.update(data)
        if len(data) < PREFIX_BYTES:
            d = h.hexdigest()
            return d, d
    return h.hexdigest(), None


def sha256_full(path):
    h = hashlib.sha256()
    with _retrying_open(path) as fh:
        while True:
            chunk = fh.read(_READ_CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _load_hashed(csv_path):
    """Map norm_key(path) -> hash-row-dict, keeping the last row per path."""
    out = {}
    if os.path.exists(csv_path):
        for row in read_csv_rows(csv_path, HASH_COLUMNS):
            out[norm_key(row["path"])] = row
    return out


def _same_identity(prev, size, mtime):
    return (prev and not prev["error"] and prev["size"] == size and
            prev["modified_utc"] == mtime)


def prune_stale_hashes(cfg, root, logger):
    """Drop hash rows for files no longer present in the inventory.

    Used after a --refresh walk: a deleted file's hash would otherwise keep
    inflating duplicate groups and appear in cross-drive comparisons as
    content that still exists. Only this tool's own CSVs are rewritten.
    """
    from .util import CsvRewriter
    live = {norm_key(r["path"]) for r in iter_inventory(cfg, root)}
    paths = hash_paths(cfg, root)
    removed_total = 0
    for key in ("prefix", "full"):
        csv_path = paths[key]
        if not os.path.exists(csv_path):
            continue
        kept = [r for r in read_csv_rows(csv_path, HASH_COLUMNS)
                if norm_key(r["path"]) in live]
        before = sum(1 for _ in read_csv_rows(csv_path, HASH_COLUMNS))
        if len(kept) == before:
            continue
        with CsvRewriter(csv_path, HASH_COLUMNS) as w:
            for r in kept:
                w.write(r)
        removed_total += before - len(kept)
    if removed_total:
        logger.info("refresh: dropped %d hash row(s) for files that no "
                    "longer exist on %s", removed_total, root)
    return removed_total


def collect_size_census(cfg, roots, dref, logger):
    """Counter of sizes across all external inventories + D reference."""
    census = Counter()
    for root in roots:
        for row in iter_inventory(cfg, root):
            if row["error"] or not row["size"]:
                continue
            size = int(row["size"])
            if size > 0:
                census[size] += 1
    for size in dref.sizes():
        census[size] += 1
    logger.info("size census: %d distinct sizes", len(census))
    return census


def run_prefix_stage(cfg, root, census, dref, logger, max_files=None):
    """Prefix-hash candidates on one drive. Resumable. Returns rows written."""
    if not os.path.isdir(root):
        logger.warning("scan root %s not present; skipping prefix stage "
                       "(re-run when attached)", root)
        return 0
    paths = hash_paths(cfg, root)
    done = _load_hashed(paths["prefix"])
    breaker = _CircuitBreaker(root, "prefix-hash")
    err_log = _Muffled(logger)
    written = 0
    with CsvAppender(paths["prefix"], HASH_COLUMNS, flush_every=200) as out:
        for row in iter_inventory(cfg, root):
            if row["error"] or not row["size"]:
                continue
            size = int(row["size"])
            if size == 0:
                continue  # zero-byte: classified as junk, not hashed
            if census[size] < 2 and not dref.has_size(size):
                continue
            if _same_identity(done.get(norm_key(row["path"])),
                              row["size"], row["modified_utc"]):
                continue
            rec = {"path": row["path"], "size": row["size"],
                   "modified_utc": row["modified_utc"],
                   "prefix_sha256": "", "full_sha256": "", "error": ""}
            try:
                pre, full = sha256_prefix(row["path"])
                rec["prefix_sha256"] = pre
                rec["full_sha256"] = full or ""
                breaker.success()
            except OSError as exc:
                rec["error"] = str(exc)
                err_log.warn("prefix hash failed for %s: %s",
                             row["path"], exc)
                breaker.failure(exc)
            out.write(rec)
            written += 1
            if written % 5000 == 0:
                logger.info("%s: prefix-hashed %d files", root, written)
            if max_files is not None and written >= max_files:
                logger.info("prefix stage stopping at max_files (resumable)")
                break
    if breaker.denied:
        logger.warning("%s: %d file(s) unreadable due to permissions during "
                       "prefix hashing - recorded with an error, excluded "
                       "from duplicate detection", root, breaker.denied)
    return written


def _iter_prefix_rows(cfg, root):
    """Stream last-written-wins prefix rows without holding them all: rows
    are appended, so a re-hashed path appears twice; downstream treats a
    second occurrence idempotently (the done-map check), so plain streaming
    is safe and keeps memory flat."""
    paths = hash_paths(cfg, root)
    if not os.path.exists(paths["prefix"]):
        return
    yield from read_csv_rows(paths["prefix"], HASH_COLUMNS)


def collect_prefix_groups(cfg, roots):
    """Counter over (size:int, prefix_sha256) across all drives' prefix CSVs.

    Uses the deduplicated per-path view so a re-hashed file counts once.
    """
    groups = Counter()
    for root in roots:
        for row in _load_hashed(hash_paths(cfg, root)["prefix"]).values():
            if row["error"] or not row["prefix_sha256"]:
                continue
            groups[(int(row["size"]), row["prefix_sha256"])] += 1
    return groups


def run_full_stage(cfg, root, prefix_groups, dref, logger, max_files=None):
    """Full-hash files whose prefix group (or D: match) requires it."""
    if not os.path.isdir(root):
        logger.warning("scan root %s not present; skipping full stage "
                       "(re-run when attached)", root)
        return 0
    paths = hash_paths(cfg, root)
    done = _load_hashed(paths["full"])
    breaker = _CircuitBreaker(root, "full-hash")
    err_log = _Muffled(logger)
    written = 0
    seen_this_run = set()
    with CsvAppender(paths["full"], HASH_COLUMNS, flush_every=100) as out:
        for row in _iter_prefix_rows(cfg, root):
            if row["error"] or not row["prefix_sha256"]:
                continue
            if row["full_sha256"]:
                continue  # small file: prefix stage already produced full hash
            size = int(row["size"])
            need = prefix_groups[(size, row["prefix_sha256"])] >= 2
            if not need and dref.has_full_hashes and dref.has_size(size):
                # a D: size match forces confirmation - unless the reference
                # carries prefix hashes proving the prefix already differs
                need = (not dref.has_prefix_hashes or
                        bool(dref.by_prefix.get((size, row["prefix_sha256"]))))
            if not need:
                continue
            key = norm_key(row["path"])
            if key in seen_this_run:
                continue  # duplicate prefix row (file was re-hashed earlier)
            seen_this_run.add(key)
            if _same_identity(done.get(key), row["size"],
                              row["modified_utc"]):
                continue
            rec = dict(row)
            rec["error"] = ""
            try:
                rec["full_sha256"] = sha256_full(row["path"])
                breaker.success()
            except OSError as exc:
                rec["full_sha256"] = ""
                rec["error"] = str(exc)
                err_log.warn("full hash failed for %s: %s", row["path"], exc)
                breaker.failure(exc)
            out.write(rec)
            written += 1
            # full hashes read whole files, so a small candidate set can
            # still take a long time - report often enough that a working
            # run is never mistaken for a hung one
            if written <= 10 or written % 25 == 0:
                logger.info("%s: full-hashed %d files", root, written)
            if max_files is not None and written >= max_files:
                logger.info("full stage stopping at max_files (resumable)")
                break
    return written


# ---------------------------------------------------------------------------
# Completeness gate: classify must not silently consume a partial hash pass
# ---------------------------------------------------------------------------

def hash_fingerprint(cfg, roots):
    """Identity of the inventory set a completed hash pass covered."""
    fp = []
    for root in sorted(roots):
        paths = inventory_paths(cfg, root)
        rows = sum(1 for _ in read_csv_rows(paths["csv"]))
        fp.append([drive_slug(root), rows])
    return fp


def _marker_path(cfg):
    return os.path.join(cfg["output_dir"], "hashes", "hash.done.json")


def write_hash_marker(cfg, roots):
    atomic_write_json(_marker_path(cfg), {"inventories":
                                          hash_fingerprint(cfg, roots)})


def check_hash_marker(cfg, roots):
    marker = load_json(_marker_path(cfg))
    current = hash_fingerprint(cfg, roots)
    if not marker or marker.get("inventories") != current:
        raise SystemExit(
            "hashing has not completed for the current inventories "
            "(interrupted, aborted, or inventories changed since). Run "
            "`python -m triage hash` to completion, then re-run classify.")


def load_all_hashes(cfg, roots):
    """norm_key(path) -> {"size", "full"} for files with a FULL hash only.

    Prefix-only entries are useless to classification (dupes require full-
    hash equality), and skipping them keeps memory proportional to the
    confirmed-candidate set instead of every size-collision on the drive.
    """
    merged = {}
    for root in roots:
        paths = hash_paths(cfg, root)
        for key, row in _load_hashed(paths["prefix"]).items():
            if row["error"] or not row["full_sha256"]:
                continue
            merged[key] = {"size": int(row["size"]),
                           "full": row["full_sha256"]}
        for key, row in _load_hashed(paths["full"]).items():
            if row["error"] or not row["full_sha256"]:
                continue
            merged[key] = {"size": int(row["size"]),
                           "full": row["full_sha256"]}
    return merged
