"""Phase 1a: full file inventory per drive -> CSV. Resumable, read-only.

Resume model: the inventory CSV itself is the state. On restart we load the
set of already-recorded paths and skip them; the walk is deterministic
(sorted) so a resumed run converges on the identical row set. A `.done`
marker records successful completion so downstream stages can trust the CSV.

Every file access is read-only (os.scandir / stat). Errors (locked files,
device hiccups on removable media) are recorded as rows with `error` set so
the inventory is still complete-by-path and the failure is visible.
"""

import errno
import os
import stat as statmod
import time

from .util import (
    INVENTORY_COLUMNS, CsvAppender, drive_slug, extended_path, iso_utc,
    norm_key, plain_path, read_csv_rows,
)

# Directories that are never user data and can recurse enormously.
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "$windows.~bt", "msocache",
}

# Above this many directories failing to list (after retries), assume the
# device/share is gone rather than that many individually bad folders.
_MAX_UNREADABLE_DIRS = 25


def inventory_paths(cfg, root):
    slug = drive_slug(root)
    base = os.path.join(cfg["output_dir"], "inventory")
    return {
        "csv": os.path.join(base, f"inventory-{slug}.csv"),
        "done": os.path.join(base, f"inventory-{slug}.done"),
        "slug": slug,
    }


def _load_seen(csv_path):
    seen = set()
    if os.path.exists(csv_path):
        for row in read_csv_rows(csv_path, INVENTORY_COLUMNS):
            seen.add(norm_key(row["path"]))
    return seen


def _is_reparse_point(entry):
    """True for NTFS junctions, mount points, symlinks, cloud placeholders.

    On Windows, DirEntry.is_symlink() is False for junctions and volume mount
    points, yet is_dir(follow_symlinks=False) is True for them - so a naive
    walk recurses THROUGH junctions: it can escape the approved scan scope
    (a preserved junction on a cloned system disk resolves against the live
    machine), loop forever on junction cycles, and catalog one physical file
    under two paths (which would fabricate a false delete-candidate dupe).
    Reparse-point files (OneDrive/dedup placeholders) must not be opened
    either: reading can trigger hydration. Everything reparse is therefore
    skipped for dirs and recorded-but-not-read for files.
    """
    st = None
    for _ in range(2):  # one retry: a USB hiccup must not mislabel a file
        try:
            st = entry.stat(follow_symlinks=False)
            break
        except OSError:
            continue
    if st is None:
        return True  # cannot prove it is safe to traverse - do not
    if getattr(st, "st_reparse_tag", 0):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    reparse_flag = getattr(statmod, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attrs & reparse_flag)


def _is_permission_error(exc):
    """True for ACL denials (Windows ERROR_ACCESS_DENIED / POSIX EACCES),
    which retrying can never fix - as opposed to device/IO errors, which
    a re-run should retry."""
    return (isinstance(exc, PermissionError) or
            getattr(exc, "winerror", None) == 5 or
            getattr(exc, "errno", None) in (errno.EACCES, errno.EPERM))


def _created_utc(st):
    """Creation time: st_birthtime where the platform provides it (and on
    Windows 3.12+ where st_ctime's meaning is changing), else st_ctime."""
    return iso_utc(getattr(st, "st_birthtime", None) or st.st_ctime)


def _walk_sorted(top, follow_symlinks, on_error, on_reparse):
    """Deterministic DFS yielding (dirpath, [file DirEntries]).

    Directory listing errors are reported via on_error and the dir skipped.
    Reparse-point entries are never traversed; files that are reparse points
    are reported via on_reparse instead of being yielded for reading.
    """
    stack = [top]
    while stack:
        d = stack.pop()
        entries = None
        last_exc = None
        # A single flaky listing (SMB hiccup, spun-down disk) should not cost
        # the whole scan, so retry before giving up on this directory.
        for attempt in range(3):
            try:
                with os.scandir(extended_path(d)) as it:
                    entries = sorted(it, key=lambda e: e.name)
                break
            except OSError as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        if entries is None:
            on_error(d, last_exc)
            continue
        files, subdirs = [], []
        for e in entries:
            full = os.path.join(d, e.name)
            try:
                if e.is_symlink() and not follow_symlinks:
                    continue
                if _is_reparse_point(e):
                    on_reparse(full, e)
                    continue
                if e.is_dir(follow_symlinks=follow_symlinks):
                    if e.name.casefold() in SKIP_DIR_NAMES:
                        continue
                    subdirs.append(full)
                elif e.is_file(follow_symlinks=follow_symlinks):
                    files.append(e)
            except OSError as exc:
                on_error(full, exc)
        yield d, files
        # push reversed so DFS visits subdirs in sorted order
        stack.extend(reversed(subdirs))


class _Muffled:
    """Log the first N occurrences of a repetitive warning at WARNING, the
    rest at DEBUG (file log only gets everything; console stays readable)."""

    def __init__(self, logger, first=20, every=1000):
        self.logger, self.first, self.every, self.n = logger, first, every, 0

    def warn(self, msg, *args):
        self.n += 1
        if self.n <= self.first or self.n % self.every == 0:
            self.logger.warning(msg + " [#%d]", *args, self.n)
        else:
            self.logger.debug(msg, *args)


def run_inventory(cfg, root, logger, max_files=None):
    """Inventory one drive. Returns (rows_written, total_rows). Read-only.

    Directory-listing failures are split by cause:
      * permission denied - an ACL that excludes even Administrator (Norton
        scratch dirs, other machines' profiles) never becomes readable by
        retrying, so the directory is RECORDED as unexamined and the scan
        completes. It surfaces in the reports and decision list, never
        silently.
      * anything else (device not ready, USB dropout, I/O error) is
        transient, so .done is withheld and a re-run retries it.
    A listing failure on the scan root itself aborts - nothing was scanned.
    """
    paths = inventory_paths(cfg, root)
    if cfg.get("_refresh"):
        # Resume is append-only, so a completed inventory never notices
        # DELETED files. A refresh starts the file list from scratch: the
        # walk is metadata-only and fast, and every hash already computed is
        # still reused (they match on path+size+mtime), so unchanged files
        # are never re-read.
        removed = 0
        for key in ("done", "csv"):
            if os.path.exists(paths[key]):
                os.remove(paths[key])   # this tool's own output only
                removed += 1
        if removed:
            logger.info("refresh: cleared previous file list for %s so "
                        "deletions are picked up (hashes are kept)", root)
    elif os.path.exists(paths["done"]):
        logger.info("inventory for %s already complete (%s)", root, paths["done"])
        return 0, sum(1 for _ in read_csv_rows(paths["csv"], INVENTORY_COLUMNS))

    seen = _load_seen(paths["csv"])
    if seen:
        logger.info("resuming inventory of %s: %d rows already recorded",
                    root, len(seen))

    written = 0
    stopped_early = False
    walk_errors = 0
    denied = []
    err_log = _Muffled(logger)
    reparse_log = _Muffled(logger)
    root_key = norm_key(root)

    def _record_unexamined(path, why):
        nonlocal written
        denied.append(path)
        if norm_key(path) not in seen:
            out.write({
                "path": plain_path(path), "size": "", "created_utc": "",
                "modified_utc": "", "ext": "",
                "error": f"{why} - directory NOT scanned; its contents "
                         f"are unknown"})
            written += 1

    def on_error(path, exc):
        nonlocal walk_errors
        if norm_key(path) == root_key:
            raise SystemExit(
                f"cannot list scan root {root}: {exc}. Is the drive "
                f"attached and readable? Nothing was scanned.")
        if _is_permission_error(exc):
            err_log.warn("permission denied, recorded as unexamined: %s",
                         path)
            _record_unexamined(path, "access denied")
            return
        # Not a permission problem, and it survived three retries. One or a
        # few such directories means those specific paths are bad (a NAS
        # recycle bin that errors on enumeration, a corrupt directory entry)
        # - record them and let the scan finish. Many of them means the
        # device or share has actually gone away, so completion is withheld.
        walk_errors += 1
        err_log.warn("cannot list %s: %s", path, exc)
        if walk_errors > _MAX_UNREADABLE_DIRS:
            raise SystemExit(
                f"{root}: {walk_errors} directories failed to list even "
                f"after retries - the drive or share looks disconnected. "
                f"State is resumable; re-run when it is healthy.")
        _record_unexamined(path, f"unreadable ({exc.__class__.__name__})")

    def on_reparse(path, entry):
        """Record reparse points without traversing/reading them."""
        nonlocal written
        try:
            is_file = entry.is_file(follow_symlinks=False)
        except OSError:
            is_file = False
        reparse_log.warn("reparse point skipped (junction/placeholder): %s",
                         path)
        if is_file and norm_key(path) not in seen:
            out.write({"path": plain_path(path), "size": "",
                       "created_utc": "", "modified_utc": "",
                       "ext": os.path.splitext(path)[1].lstrip(".").lower(),
                       "error": "reparse-point file (not read)"})
            written += 1

    with CsvAppender(paths["csv"], INVENTORY_COLUMNS) as out:
        for dirpath, files in _walk_sorted(root, cfg["follow_symlinks"],
                                           on_error, on_reparse):
            for entry in files:
                full = os.path.join(dirpath, entry.name)
                if norm_key(full) in seen:
                    continue
                row = {"path": plain_path(full), "error": ""}
                try:
                    st = entry.stat(follow_symlinks=cfg["follow_symlinks"])
                    if not statmod.S_ISREG(st.st_mode):
                        continue
                    row["size"] = st.st_size
                    row["created_utc"] = _created_utc(st)
                    row["modified_utc"] = iso_utc(st.st_mtime)
                except OSError as exc:
                    row["size"] = ""
                    row["created_utc"] = row["modified_utc"] = ""
                    row["error"] = str(exc)
                    err_log.warn("stat failed for %s: %s", full, exc)
                ext = os.path.splitext(entry.name)[1].lstrip(".").lower()
                row["ext"] = ext
                out.write(row)
                written += 1
                if written % 20000 == 0:
                    logger.info("%s: %d new rows (last dir: %s)",
                                root, written, dirpath)
                if max_files is not None and written >= max_files:
                    logger.info("stopping after max_files=%d (resumable)",
                                max_files)
                    stopped_early = True
                    break
            if stopped_early:
                break

    if denied:
        logger.warning(
            "%s: %d directory(ies) could not be read and are recorded as "
            "UNEXAMINED (contents unknown): %s", root,
            len(denied), "; ".join(denied[:10]))
    if stopped_early:
        pass
    else:
        with open(paths["done"], "w", encoding="utf-8") as fh:
            fh.write("complete\n")
        logger.info("inventory of %s complete: %d new rows (%d unexamined "
                    "permission-denied directories)", root, written,
                    len(denied))
    return written, written + len(seen)


def iter_inventory(cfg, root):
    """Stream completed inventory rows for a drive (error rows included).

    A generator so multi-million-file drives never need the whole inventory
    in memory; call it again for another pass.
    """
    paths = inventory_paths(cfg, root)
    if not os.path.exists(paths["done"]):
        raise SystemExit(
            f"inventory for {root} is not complete; run `inventory` first "
            f"(it resumes automatically).")
    yield from read_csv_rows(paths["csv"], INVENTORY_COLUMNS)
