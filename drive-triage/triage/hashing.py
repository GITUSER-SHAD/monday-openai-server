"""Phase 1b: two-stage duplicate hashing. Read-only, resumable per drive.

Stage 1 (cheap): a file is a *candidate* only if its size occurs more than
once across (all external inventories + the D: reference set). Candidates get
a SHA256 of their first 64KB ("prefix hash").

Stage 2 (expensive): full SHA256 only where it can decide something -
  * the (size, prefix) group has >= 2 external members, or
  * the size matches a D: reference entry that carries a full SHA256.
Files <= 64KB are finished in stage 1 (prefix hash IS the full hash).

Resume model: per-drive append-only CSVs (prefix-<slug>.csv, full-<slug>.csv);
on restart, already-hashed paths (matching size) are skipped.
"""

import hashlib
import os
import time
from collections import Counter

from .util import (
    HASH_COLUMNS, PREFIX_BYTES, CsvAppender, drive_slug, extended_path,
    norm_key, read_csv_rows,
)
from .inventory import iter_inventory

_READ_CHUNK = 1024 * 1024


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
    """Map norm_key(path) -> (size, hash-row-dict), keeping the last row."""
    out = {}
    if os.path.exists(csv_path):
        for row in read_csv_rows(csv_path, HASH_COLUMNS):
            out[norm_key(row["path"])] = row
    return out


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
    paths = hash_paths(cfg, root)
    done = _load_hashed(paths["prefix"])
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
            key = norm_key(row["path"])
            prev = done.get(key)
            if prev and prev["size"] == row["size"] and not prev["error"]:
                continue
            rec = {"path": row["path"], "size": row["size"],
                   "modified_utc": row["modified_utc"],
                   "prefix_sha256": "", "full_sha256": "", "error": ""}
            try:
                pre, full = sha256_prefix(row["path"])
                rec["prefix_sha256"] = pre
                rec["full_sha256"] = full or ""
            except OSError as exc:
                rec["error"] = str(exc)
                logger.warning("prefix hash failed for %s: %s",
                               row["path"], exc)
            out.write(rec)
            written += 1
            if written % 5000 == 0:
                logger.info("%s: prefix-hashed %d files", root, written)
            if max_files is not None and written >= max_files:
                logger.info("prefix stage stopping at max_files (resumable)")
                break
    return written


def collect_prefix_groups(cfg, roots):
    """Counter over (size:int, prefix_sha256) across all drives' prefix CSVs."""
    groups = Counter()
    for root in roots:
        paths = hash_paths(cfg, root)
        for row in _load_hashed(paths["prefix"]).values():
            if row["error"] or not row["prefix_sha256"]:
                continue
            groups[(int(row["size"]), row["prefix_sha256"])] += 1
    return groups


def run_full_stage(cfg, root, prefix_groups, dref, logger, max_files=None):
    """Full-hash files whose prefix group (or D: match) requires it."""
    paths = hash_paths(cfg, root)
    done = _load_hashed(paths["full"])
    written = 0
    with CsvAppender(paths["full"], HASH_COLUMNS, flush_every=100) as out:
        for row in _load_hashed(paths["prefix"]).values():
            if row["error"] or not row["prefix_sha256"]:
                continue
            if row["full_sha256"]:
                continue  # small file: prefix stage already produced full hash
            size = int(row["size"])
            need = prefix_groups[(size, row["prefix_sha256"])] >= 2
            if not need and dref.has_full_hashes and dref.has_size(size):
                need = True
            if not need:
                continue
            key = norm_key(row["path"])
            prev = done.get(key)
            if prev and prev["size"] == row["size"] and not prev["error"]:
                continue
            rec = dict(row)
            rec["error"] = ""
            try:
                rec["full_sha256"] = sha256_full(row["path"])
            except OSError as exc:
                rec["full_sha256"] = ""
                rec["error"] = str(exc)
                logger.warning("full hash failed for %s: %s", row["path"], exc)
            out.write(rec)
            written += 1
            if written % 1000 == 0:
                logger.info("%s: full-hashed %d files", root, written)
            if max_files is not None and written >= max_files:
                logger.info("full stage stopping at max_files (resumable)")
                break
    return written


def load_all_hashes(cfg, roots):
    """norm_key(path) -> {"size", "prefix", "full"} merged from both stages."""
    merged = {}
    for root in roots:
        paths = hash_paths(cfg, root)
        for key, row in _load_hashed(paths["prefix"]).items():
            if row["error"]:
                continue
            merged[key] = {"size": int(row["size"]),
                           "prefix": row["prefix_sha256"],
                           "full": row["full_sha256"] or None}
        for key, row in _load_hashed(paths["full"]).items():
            if row["error"] or not row["full_sha256"]:
                continue
            if key in merged:
                merged[key]["full"] = row["full_sha256"]
            else:
                merged[key] = {"size": int(row["size"]),
                               "prefix": row["prefix_sha256"],
                               "full": row["full_sha256"]}
    return merged
