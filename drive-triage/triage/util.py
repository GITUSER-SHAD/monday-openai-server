"""Shared utilities: config, logging, CSV I/O, checkpoints, read-only guards.

Design rules enforced here:
  * No network imports anywhere in this package (tested by tests/test_security.py).
  * All writes are confined to config output_dir / log_dir, which must lie
    outside every scan root (guard_output_dirs).
  * Checkpoint/state writes are atomic (temp file + os.replace) so a crash
    mid-write never corrupts resume state.
"""

import csv
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# Row schemas (column orders are part of the resume contract - do not reorder)
# ---------------------------------------------------------------------------

INVENTORY_COLUMNS = [
    "path",          # absolute path on the scanned drive
    "size",          # bytes; empty on stat error
    "created_utc",   # ISO8601; on Windows st_ctime is creation time
    "modified_utc",  # ISO8601
    "ext",           # lowercased extension without dot ("" if none)
    "error",         # stat/read error message, empty if OK
]

HASH_COLUMNS = [
    "path",
    "size",
    "modified_utc",   # identity check for resume: path+size+mtime must match
    "prefix_sha256",  # SHA256 of first PREFIX_BYTES (or whole file if smaller)
    "full_sha256",    # SHA256 of whole file; empty if only prefix stage ran
    "error",
]

CLASSIFY_COLUMNS = [
    "path",
    "size",
    "drive",           # scan root this file came from
    "class",           # one of CLASSES
    "subclass",        # bucket detail, e.g. media/records subcategory, junk kind
    "dupe_of",         # for dupe classes: canonical keeper / D: reference path
    "proposed_path",   # target folder in the approved taxonomy (backslash form)
    "proposed_name",   # convention-compliant filename ("" = keep current name)
    "nas_tier",        # fastwork | hdd-mirror | none
    "confidence",      # high | medium | low
    "evidence",        # human-readable reason, always populated
]

MANIFEST_COLUMNS = [
    "action",          # copy | hold | delete-candidate
    "source_path",
    "proposed_path",
    "proposed_name",
    "nas_tier",
    "class",
    "subclass",
    "size",
    "confidence",
    "evidence",
]

CLASSES = [
    "EXACT_DUPE_OF_D",   # byte-identical to a file in the D: reference set
    "DUPE_EXTERNAL",     # duplicate within/across external drives (non-keeper)
    "MEDIA",             # elected keepers of dupe groups keep their content
    "RECORDS",           # class; evidence records their keeper status
    "ARCHIVE_BOX",       # member of an intact archive box (box moves whole)
    "JUNK",
    "UNKNOWN",
]

PREFIX_BYTES = 64 * 1024

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    # Directories this tool WRITES to. Must be outside every scan root.
    "output_dir": "C:\\DEV\\triage" if IS_WINDOWS else "./triage-output",
    "log_dir": "C:\\DEV\\logs\\drive-triage" if IS_WINDOWS else "./triage-output/logs",
    # Freshest D: inventory CSV (post-reorg reference set for dupe detection).
    "d_reference_csv": "",
    # Scan roots (drive letters like "E:\\" or fixture directories). Populated
    # from the approved Phase 0 scope; never includes C: or D: by default.
    "scan_roots": [],
    # Media projects modified within this many days are proposed for the
    # NVMe fastwork tier; older ones go to the HDD mirror.
    "active_project_days": 548,  # ~18 months
    # Case-insensitive substrings marking a shoot as personal rather than client.
    "personal_shoot_keywords": [
        "personal", "family", "vacation", "holiday", "wedding own", "home video",
    ],
    # On Windows, output/log dirs must live on the system drive (C:) unless
    # this is explicitly set true - external drives are strictly read-only.
    "allow_output_off_system_drive": False,
    # Known client codes, e.g. {"ACME": "Acme Corp"} -> Records\Business\Clients\ACME Acme Corp
    "client_codes": {},
    "checkpoint_every_files": 2000,
    "follow_symlinks": False,
}


def load_config(path):
    cfg = dict(DEFAULT_CONFIG)
    if path:
        with open(path, "r", encoding="utf-8-sig") as fh:
            user_cfg = json.load(fh)
        unknown = set(user_cfg) - set(DEFAULT_CONFIG)
        if unknown:
            raise SystemExit(f"config: unknown keys {sorted(unknown)}")
        cfg.update(user_cfg)
    return cfg


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def norm_key(path):
    """Canonical form for identity comparisons (Windows is case-insensitive)."""
    p = os.path.normpath(os.path.abspath(path))
    return p.casefold() if IS_WINDOWS else p


def extended_path(path):
    """Wrap absolute Windows paths with \\\\?\\ so >260-char paths work."""
    if not IS_WINDOWS:
        return path
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):           # UNC
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def plain_path(path):
    """Undo extended_path for storage in CSVs (human-readable form)."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def is_under(child, parent):
    c, p = norm_key(child), norm_key(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _canonical(path):
    """Resolve to a canonical real path: realpath resolves symlinks, NTFS
    junctions and subst mappings, and strips \\\\?\\ spellings - so aliased
    forms of a scan root cannot slip past the prefix comparison."""
    return os.path.realpath(plain_path(os.path.abspath(path)))


def _volume_id(path):
    """st_dev of the nearest existing ancestor (volume serial on Windows)."""
    p = _canonical(path)
    while True:
        try:
            return os.stat(p).st_dev
        except OSError:
            parent = os.path.dirname(p)
            if parent == p:
                return None
            p = parent


_DRIVE_ROOT = re.compile(r"^[A-Za-z]:[\\/]?$")


def guard_output_dirs(cfg):
    """Refuse to run if output/log dirs could land on a scanned drive.

    Two independent checks per (scan root, output dir) pair:
      1. canonical-path prefix (realpath both sides, defeating \\\\?\\ / UNC /
         subst / junction aliases of the same location);
      2. when the scan root is a whole drive (E:\\), volume identity - any
         output dir whose nearest existing ancestor lives on that volume is
         refused even if its path spells the location differently.
    """
    if IS_WINDOWS and not cfg.get("allow_output_off_system_drive"):
        sys_vol = _volume_id(os.environ.get("SystemDrive", "C:") + "\\")
        for name in ("output_dir", "log_dir"):
            if sys_vol is not None and _volume_id(cfg[name]) != sys_vol:
                raise SystemExit(
                    f"REFUSING TO RUN: {name} ({cfg[name]}) is not on the "
                    f"system drive. External drives are strictly read-only; "
                    f"keep outputs on C: (or set "
                    f"allow_output_off_system_drive in the config if you "
                    f"know the target volume is safe)."
                )
    for root in cfg["scan_roots"]:
        root_canon = _canonical(root)
        whole_drive = bool(_DRIVE_ROOT.match(root.strip()))
        root_vol = _volume_id(root) if whole_drive else None
        for name in ("output_dir", "log_dir"):
            target = cfg[name]
            offending = is_under(_canonical(target), root_canon)
            if not offending and whole_drive and root_vol is not None:
                offending = _volume_id(target) == root_vol
            if offending:
                raise SystemExit(
                    f"REFUSING TO RUN: {name} ({target}) resolves onto scan "
                    f"root {root}. Scanned drives are strictly read-only; "
                    f"point {name} at a directory on the system drive."
                )


def drive_slug(root):
    """Stable per-drive identifier for output filenames: 'E' or dir basename."""
    root = root.rstrip("\\/")
    if re.fullmatch(r"[A-Za-z]:", root):
        return root[0].upper()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", os.path.basename(root) or root)
    return slug or "drive"


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def iso_utc(epoch):
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return ""


def now_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# Logging: verbose output goes to files, chat/console stays quiet
# ---------------------------------------------------------------------------

def setup_logging(log_dir, name):
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fh = logging.FileHandler(
        os.path.join(log_dir, f"{name}-{now_stamp()}.log"), encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.WARNING)  # console: warnings and errors only
    ch.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# CSV I/O - append-friendly, resume-friendly
# ---------------------------------------------------------------------------

class CsvAppender:
    """Append rows to a CSV, writing the header only on creation.

    Rows are flushed (and fsync'd) every `flush_every` rows so a crash loses
    at most that many rows; resume logic tolerates a torn final line.
    """

    def __init__(self, path, columns, flush_every=500):
        self.path = path
        self.columns = columns
        self.flush_every = flush_every
        self._count = 0
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        exists = os.path.exists(path) and os.path.getsize(path) > 0
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh)
        if not exists:
            self._writer.writerow(columns)
            self._flush()

    def write(self, row_dict):
        self._writer.writerow([row_dict.get(c, "") for c in self.columns])
        self._count += 1
        if self._count % self.flush_every == 0:
            self._flush()

    def _flush(self):
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self):
        self._flush()
        self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_csv_rows(path, expect_columns=None):
    """Yield dict rows; tolerate a torn final line from a crashed run."""
    with open(path, "r", newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            return
        if expect_columns and [h.strip() for h in header] != expect_columns:
            raise SystemExit(
                f"{path}: unexpected columns {header!r}; expected "
                f"{expect_columns!r}. Wrong file or produced by a different "
                f"tool version - refusing to mix.")
        ncol = len(header)
        for row in reader:
            if len(row) != ncol:
                continue  # torn tail line from an interrupted run
            yield dict(zip(header, row))


def atomic_write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def fmt_gb(nbytes):
    return f"{nbytes / (1024 ** 3):.2f} GB"


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
