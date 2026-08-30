"""Phase 1a: full file inventory per drive -> CSV. Resumable, read-only.

Resume model: the inventory CSV itself is the state. On restart we load the
set of already-recorded paths and skip them; the walk is deterministic
(sorted) so a resumed run converges on the identical row set. A `.done`
marker records successful completion so downstream stages can trust the CSV.

Every file access is read-only (os.scandir / stat). Errors (locked files,
device hiccups on removable media) are recorded as rows with `error` set so
the inventory is still complete-by-path and the failure is visible.
"""

import os
import stat as statmod

from .util import (
    INVENTORY_COLUMNS, CsvAppender, drive_slug, extended_path, iso_utc,
    norm_key, plain_path, read_csv_rows,
)

# Directories that are never user data and can recurse enormously.
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", "$windows.~bt", "msocache",
}


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


def _walk_sorted(top, follow_symlinks, on_error):
    """Deterministic DFS yielding (dirpath, [file DirEntries]).

    Directory listing errors are reported via on_error and the dir skipped.
    """
    stack = [top]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(extended_path(d)) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError as exc:
            on_error(d, exc)
            continue
        files, subdirs = [], []
        for e in entries:
            try:
                if e.is_symlink() and not follow_symlinks:
                    continue
                if e.is_dir(follow_symlinks=follow_symlinks):
                    if e.name.casefold() in SKIP_DIR_NAMES:
                        continue
                    subdirs.append(os.path.join(d, e.name))
                elif e.is_file(follow_symlinks=follow_symlinks):
                    files.append(e)
            except OSError as exc:
                on_error(os.path.join(d, e.name), exc)
        yield d, files
        # push reversed so DFS visits subdirs in sorted order
        stack.extend(reversed(subdirs))


def run_inventory(cfg, root, logger, max_files=None):
    """Inventory one drive. Returns (rows_written, total_rows). Read-only."""
    paths = inventory_paths(cfg, root)
    if os.path.exists(paths["done"]):
        logger.info("inventory for %s already complete (%s)", root, paths["done"])
        return 0, sum(1 for _ in read_csv_rows(paths["csv"], INVENTORY_COLUMNS))

    seen = _load_seen(paths["csv"])
    if seen:
        logger.info("resuming inventory of %s: %d rows already recorded",
                    root, len(seen))

    written = 0
    stopped_early = False

    def on_error(path, exc):
        logger.warning("cannot list %s: %s", path, exc)

    with CsvAppender(paths["csv"], INVENTORY_COLUMNS) as out:
        for dirpath, files in _walk_sorted(root, cfg["follow_symlinks"], on_error):
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
                    row["created_utc"] = iso_utc(st.st_ctime)
                    row["modified_utc"] = iso_utc(st.st_mtime)
                except OSError as exc:
                    row["size"] = ""
                    row["created_utc"] = row["modified_utc"] = ""
                    row["error"] = str(exc)
                    logger.warning("stat failed for %s: %s", full, exc)
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

    if not stopped_early:
        with open(paths["done"], "w", encoding="utf-8") as fh:
            fh.write("complete\n")
        logger.info("inventory of %s complete: %d new rows", root, written)
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
