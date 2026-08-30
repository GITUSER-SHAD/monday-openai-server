"""D: reference set loading + duplicate group resolution.

The D: inventory CSV comes from the separate D: reorg tooling, so its exact
columns are unknown; DReference sniffs delimiter and maps columns by common
header names. If the reference carries full SHA256 hashes, exact-dupe-of-D
classification is byte-certain. If it only has sizes/names, D-matches are
reported as PROBABLE (size+filename) and routed to the decision list, plus a
`d-hash-request.csv` is emitted listing the D: paths whose hashes would
upgrade those matches to certain.
"""

import csv
import os
import re
from collections import defaultdict

from .util import norm_key

_PATH_HEADERS = ("path", "fullpath", "full_path", "fullname", "full_name",
                 "filepath", "file_path")
# NOT "filename": that header conventionally holds a bare basename, which
# would make every dupe_of reference unverifiable.
_SIZE_HEADERS = ("size", "size_bytes", "length", "bytes", "filesize",
                 "file_size")
_FULL_HASH_HEADERS = ("sha256", "full_sha256", "hash", "sha_256", "sha256sum",
                      "fullhash", "full_hash")
_PREFIX_HASH_HEADERS = ("prefix_sha256", "prefix_hash", "head_sha256")


def _squash(s):
    """Lowercase, alphanumerics only - so 'SizeBytes', 'size_bytes', and
    'Size Bytes' all compare equal regardless of the source tool's naming
    convention (PowerShell CSVs commonly use PascalCase with no separator)."""
    return re.sub(r"[^a-z0-9]", "", s.strip().lower())


def _match_header(headers, wanted):
    squashed = {_squash(h): h for h in headers}
    for w in wanted:
        if _squash(w) in squashed:
            return squashed[_squash(w)]
    return None


class DReference:
    """Indexed view of the D: post-reorg inventory."""

    def __init__(self):
        self.by_full = defaultdict(list)     # full sha256 -> [d_path]
        self.by_prefix = defaultdict(list)   # (size, prefix) -> [d_path]
        self.by_size_name = defaultdict(list)  # (size, name.casefold()) -> [d_path]
        self._sizes = set()
        self.has_full_hashes = False
        self.has_prefix_hashes = False
        self.row_count = 0
        self.source = ""

    @classmethod
    def empty(cls):
        return cls()

    @classmethod
    def load(cls, csv_path, logger):
        ref = cls()
        if not csv_path:
            logger.warning(
                "no d_reference_csv configured: exact-dupe-of-D detection is "
                "OFF; only external cross/within-drive dupes will be found")
            return ref
        ref.source = csv_path
        with open(csv_path, "r", newline="", encoding="utf-8-sig",
                  errors="replace") as fh:
            sample = fh.read(64 * 1024)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(fh, dialect)
            try:
                headers = next(reader)
            except StopIteration:
                raise SystemExit(f"{csv_path}: empty reference CSV")
            col_path = _match_header(headers, _PATH_HEADERS)
            col_size = _match_header(headers, _SIZE_HEADERS)
            col_full = _match_header(headers, _FULL_HASH_HEADERS)
            col_prefix = _match_header(headers, _PREFIX_HASH_HEADERS)
            if not col_path or not col_size:
                raise SystemExit(
                    f"{csv_path}: could not identify path/size columns in "
                    f"{headers!r}. Recognized path headers: {_PATH_HEADERS}; "
                    f"size headers: {_SIZE_HEADERS}.")
            idx = {h: i for i, h in enumerate(headers)}
            for row in reader:
                if len(row) != len(headers):
                    continue
                path = row[idx[col_path]].strip()
                if not path:
                    continue
                raw_size = row[idx[col_size]].strip()
                size = int(raw_size) if re.fullmatch(r"\d+", raw_size) \
                    else None
                if col_full:
                    h = row[idx[col_full]].strip().lower()
                    if re.fullmatch(r"[0-9a-f]{64}", h):
                        # full-hash matching works even when the size field
                        # is malformed - don't throw the hash away
                        ref.by_full[h].append(path)
                        ref.has_full_hashes = True
                        ref.row_count += 1 if size is None else 0
                if size is None or size == 0:
                    continue
                ref.row_count += 1
                ref._sizes.add(size)
                name = os.path.basename(path).casefold()
                ref.by_size_name[(size, name)].append(path)
                if col_prefix:
                    h = row[idx[col_prefix]].strip().lower()
                    if re.fullmatch(r"[0-9a-f]{64}", h):
                        ref.by_prefix[(size, h)].append(path)
                        ref.has_prefix_hashes = True
        logger.info(
            "D reference loaded: %d rows from %s (full hashes: %s)",
            ref.row_count, csv_path, ref.has_full_hashes)
        return ref

    def drop_paths_under(self, roots, logger):
        """Remove reference entries that lie under a scan root. If the
        configured D: reference CSV actually covers a drive being scanned,
        every file on it would otherwise become an 'exact dupe of D:' of
        itself - a fabricated delete-candidate for the only copy."""
        from .util import is_under  # local import avoids a cycle at load

        def keep(path):
            return not any(is_under(path, r) for r in roots)

        dropped = 0
        for index in (self.by_full, self.by_prefix, self.by_size_name):
            for k in list(index):
                kept = [p for p in index[k] if keep(p)]
                dropped += len(index[k]) - len(kept)
                if kept:
                    index[k] = kept
                else:
                    del index[k]
        if dropped:
            logger.warning(
                "D reference: dropped %d entries that lie under a scan root "
                "(the reference must describe D:, not a drive being "
                "triaged)", dropped)
            self._sizes = {k[0] for k in self.by_size_name} | \
                {k[0] for k in self.by_prefix}
            self.has_full_hashes = bool(self.by_full)
            self.has_prefix_hashes = bool(self.by_prefix)
        return dropped

    def has_size(self, size):
        return size in self._sizes

    def sizes(self):
        return self._sizes

    def match_full(self, full_sha256):
        return self.by_full.get(full_sha256, [])

    def match_size_name(self, size, name):
        return self.by_size_name.get((size, name.casefold()), [])


# ---------------------------------------------------------------------------
# Duplicate resolution across externals
# ---------------------------------------------------------------------------

_TAXONOMY_PAT = re.compile(
    r"[\\/](media[\\/](19|20)\d\d|records[\\/]|archive[\\/])", re.IGNORECASE)
_GENERIC_DIRS = {
    "new folder", "untitled", "misc", "stuff", "temp", "tmp", "desktop",
    "downloads", "backup", "backups", "copy", "old", "unsorted",
    "cache", "caches",  # never elect the cache-dir copy as the keeper
}


def _keeper_score(path, mtime):
    """Deterministic keeper election for an external dupe group.

    Prefer: already-taxonomy-shaped paths > descriptive (non-generic) parent
    dirs > deeper organization > newer mtime > lexicographic tiebreak.
    """
    parent = os.path.basename(os.path.dirname(path)).casefold()
    return (
        1 if _TAXONOMY_PAT.search(path) else 0,
        0 if parent in _GENERIC_DIRS else 1,
        min(path.count("\\") + path.count("/"), 8),
        mtime or "",
        # invert lexicographic so max() is deterministic on full ties
        tuple(-ord(c) for c in path[:64]),
    )


def resolve_dupe_groups(files, dref):
    """Classify duplicate relationships.

    `files`: list of dicts with keys path, size(int), mtime, full(sha or None).
    Returns (d_dupes, ext_dupes, keepers):
      d_dupes:   norm_key -> d_reference_path        (byte-certain, via SHA256)
      ext_dupes: norm_key -> keeper_path             (non-keepers only)
      keepers:   norm_key -> group_size              (elected keepers, group>1)
    Probable (size+name) matches vs a hash-less D: reference are computed
    separately by probable_d_matches over the full inventory.
    """
    d_dupes = {}
    by_full = defaultdict(list)

    for f in files:
        if not f["full"]:
            continue
        d_paths = dref.match_full(f["full"])
        if d_paths:
            d_dupes[norm_key(f["path"])] = d_paths[0]
            continue
        by_full[(f["size"], f["full"])].append(f)

    ext_dupes, keepers = {}, {}
    for group in by_full.values():
        if len(group) < 2:
            continue
        best = max(group, key=lambda f: _keeper_score(f["path"], f["mtime"]))
        keepers[norm_key(best["path"])] = len(group)
        for f in group:
            if f is not best:
                ext_dupes[norm_key(f["path"])] = best["path"]
    return d_dupes, ext_dupes, keepers


def probable_d_matches(cfg, roots, dref, iter_rows):
    """size+basename matches vs a hash-less D: reference, over ALL files.

    `iter_rows(root)` streams inventory rows. Only meaningful when the
    reference lacks full hashes; returns norm_key -> d_reference_path.
    """
    probable = {}
    if dref.has_full_hashes or not dref.row_count:
        return probable
    for root in roots:
        for row in iter_rows(root):
            if row["error"] or not row["size"]:
                continue
            size = int(row["size"])
            if size == 0:
                continue
            d_paths = dref.match_size_name(size,
                                           os.path.basename(row["path"]))
            if d_paths:
                probable[norm_key(row["path"])] = d_paths[0]
    return probable


def write_d_hash_request(cfg, probable_d, logger):
    """Emit the list of D: paths whose SHA256 would confirm probable dupes."""
    if not probable_d:
        return None
    out = os.path.join(cfg["output_dir"], "d-hash-request.csv")
    d_paths = sorted(set(probable_d.values()))
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["d_path"])
        for p in d_paths:
            w.writerow([p])
    logger.info("wrote %d D: paths needing hashes -> %s", len(d_paths), out)
    return out
