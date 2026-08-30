"""Phase 2: classify every inventoried file. Pure computation over the
Phase 1 CSVs - touches no target-drive bytes (hashing already did the reads).

Precedence per file:
  stat-error -> UNKNOWN
  archive-box member -> ARCHIVE_BOX (box stays intact; junk-within-box and
      sole-surviving content are annotated in evidence, never re-sorted)
  zero-byte -> JUNK
  exact SHA256 match vs D: reference -> EXACT_DUPE_OF_D
  non-keeper of an external dupe group -> DUPE_EXTERNAL
  junk patterns -> JUNK (pattern evidence stated)
  media extensions -> MEDIA (year/project parsed; personal vs client;
      NAS tier + fastwork subfolder mapping)
  records extensions -> RECORDS (subcategory + convention-compliant rename)
  else -> UNKNOWN (grouped for the decision list)

Every row carries `evidence`. Keepers of dupe groups are classified by
content with keeper status noted in evidence.
"""

import os
import re

from .util import CLASSIFY_COLUMNS, CsvAppender, drive_slug, norm_key
from .inventory import iter_inventory
from .hashing import load_all_hashes
from .dupes import (
    probable_d_matches, resolve_dupe_groups, write_d_hash_request,
)

# ---------------------------------------------------------------------------
# Extension sets
# ---------------------------------------------------------------------------

RAW_PHOTO_EXT = {"cr2", "cr3", "crw", "nef", "nrw", "arw", "dng", "raf",
                 "orf", "rw2", "pef", "srw", "x3f"}
PHOTO_EXT = {"jpg", "jpeg", "png", "tif", "tiff", "heic", "heif", "bmp",
             "gif", "webp", "psd", "xmp"}
VIDEO_EXT = {"mp4", "mov", "avi", "mts", "m2ts", "mxf", "braw", "r3d", "mkv",
             "wmv", "m4v", "mpg", "mpeg", "3gp", "crm", "insv", "lrf"}
AUDIO_EXT = {"wav", "mp3", "aac", "flac", "m4a", "aif", "aiff", "ogg"}
PROJECT_EXT = {"prproj", "aep", "drp", "fcpxml", "veg", "psd", "ai",
               "aaf", "edl", "xml"}
MEDIA_EXT = RAW_PHOTO_EXT | PHOTO_EXT | VIDEO_EXT | AUDIO_EXT | PROJECT_EXT

DOC_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "csv", "txt", "rtf", "odt",
           "ods", "eml", "msg"}
SCANNED_RECORD_HINTS = re.compile(
    r"(receipt|invoice|scan|statement|contract|estimate|quote|w-?9|1099|"
    r"w-?2|tax|registration|title|insurance|warranty|license|permit)",
    re.IGNORECASE)

INSTALLER_EXT = {"exe", "msi", "msix", "msu", "appx"}
INSTALLER_NAME = re.compile(
    r"(setup|install|installer|redist|vc_redist|dxwebsetup|driver|"
    r"webinstall|offline.?installer|update|patch|upgrade|"
    r"x(64|86)|win(32|64)|_v?\d+(\.\d+){1,3})", re.IGNORECASE)
INSTALLER_DIRS = {"downloads", "installers", "drivers", "software", "setup",
                  "apps", "programs", "utilities", "distrib"}

JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini", "iconcache.db",
              ".picasa.ini", "picasa.ini", "zbthumbnail.info",
              "albumartsmall.jpg", "folder.jpg"}
JUNK_EXT = {"tmp", "temp", "crdownload", "part", "partial", "dmp", "chk",
            "etl", "regtrans-ms", "blf"}
CACHE_DIRS = {"cache", "caches", ".cache", "temp", "tmp", ".thumbnails",
              "thumbnails", "node_modules", "__pycache__", ".gradle",
              "packages", "servicepackfiles", "softwaredistribution"}

BACKUP_IMAGE_EXT = {"tib", "tibx", "vhd", "vhdx", "wim", "bkf", "spf", "spi",
                    "gho", "v2i", "swstor"}

# ---------------------------------------------------------------------------
# Archive-box detection (directory-level, evidence-based)
# ---------------------------------------------------------------------------

SYSTEMISH_TOPDIRS = {
    "users", "windows", "program files", "program files (x86)", "programdata",
    "appdata", "documents and settings", "windows.old", "intel", "perflogs",
    "recovery", "boot", "system32", "inetpub",
}
BACKUPISH_NAME = re.compile(
    r"(backup|bkup|bckup|my ?book|smartware|file ?history|migration|clone|"
    r"old[ _-]?(laptop|pc|computer|desktop|drive|mac)|"
    r"(laptop|pc|computer|desktop|c[ _-]?drive)[ _-]?(backup|copy|dump)|"
    r"time ?machine|\.swstor)", re.IGNORECASE)
VERSION_STORE_DIRNAMES = {"history", "filehistory", "file history",
                          "$archive$", "versions"}
VERSIONED_FILE = re.compile(
    r"(\(\d{4}[_-]\d{2}[_-]\d{2}[ _]\d{2}[_-]\d{2}[_-]\d{2}( utc)?\)|"
    r"\.v\d{2,}$|\(\d+\)\.[A-Za-z0-9]{1,5}$)", re.IGNORECASE)
PROFILE_MARKERS = {"ntuser.dat", "ntuser.ini", "usrclass.dat"}


def _split_rel(root, path):
    rel = os.path.relpath(path, root)
    return re.split(r"[\\/]", rel) if rel != "." else []


class BoxMap:
    """Maps files to detected archive boxes on one drive."""

    def __init__(self):
        self.boxes = {}          # box_key -> {"name","evidence","prefixes"}
        self._prefix_index = []  # (prefix_tuple, box_key)

    def add_box(self, key, name, evidence, prefixes):
        if key in self.boxes:
            self.boxes[key]["prefixes"].update(prefixes)
        else:
            self.boxes[key] = {"name": name, "evidence": evidence,
                               "prefixes": set(prefixes)}

    def finalize(self):
        self._prefix_index = sorted(
            ((tuple(s.casefold() for s in re.split(r"[\\/]", p)), k)
             for k, b in self.boxes.items() for p in b["prefixes"]),
            key=lambda t: -len(t[0]))  # longest prefix wins

    def lookup(self, rel_parts):
        low = tuple(s.casefold() for s in rel_parts)
        for prefix, key in self._prefix_index:
            if low[:len(prefix)] == prefix:
                return key
        return None


def detect_boxes(root, rows, logger):
    """Scan a drive's inventory rows (single pass; generator-friendly) and
    find archive-box roots. Memory stays proportional to directory count,
    not file count."""
    slug = drive_slug(root)
    box = BoxMap()
    dirs_seen = set()
    marker_dirs = set()      # dirs containing NTUSER.DAT-style files
    versioned_counts = {}    # version-store-named dir -> versioned-file count
    image_files = []         # standalone backup images

    for row in rows:
        parts = _split_rel(root, row["path"])
        if not parts:
            continue
        for i in range(1, len(parts)):
            dirs_seen.add(tuple(parts[:i]))
        d = tuple(parts[:-1])
        name_low = parts[-1].casefold()
        if name_low in PROFILE_MARKERS:
            marker_dirs.add(d)
        if d and d[-1].casefold() in VERSION_STORE_DIRNAMES and \
                VERSIONED_FILE.search(parts[-1]):
            versioned_counts[d] = versioned_counts.get(d, 0) + 1
        if row["ext"] in BACKUP_IMAGE_EXT:
            image_files.append((parts, row["ext"]))

    systemish_top = set()
    for d in dirs_seen:
        base = d[-1].casefold()
        top = d[0]
        top_low = top.casefold()

        if len(d) == 1 and top_low in SYSTEMISH_TOPDIRS:
            systemish_top.add(top)
            continue
        if len(d) == 1 and BACKUPISH_NAME.search(top):
            box.add_box(f"top:{top_low}", top,
                        f"top-level folder name matches backup pattern "
                        f"({BACKUPISH_NAME.search(top).group(0)!r})", {top})
            continue
        # profile marker (AppData / NTUSER.DAT) buried under a top-level dir
        if base == "appdata" and len(d) >= 2:
            box.add_box(f"top:{top_low}", top,
                        f"contains user-profile marker dir "
                        f"{'/'.join(d)} (AppData)", {top})
        if d in marker_dirs and len(d) >= 2:
            box.add_box(f"top:{top_low}", top,
                        f"contains profile marker file under {'/'.join(d)}",
                        {top})
        # version stores (WD SmartWare History, Windows File History)
        if base in VERSION_STORE_DIRNAMES:
            versioned = versioned_counts.get(d, 0)
            if versioned >= 3 or ".swstor" in " ".join(d).casefold():
                box.add_box(f"top:{top_low}", top,
                            f"version store {'/'.join(d)} "
                            f"({versioned} versioned filenames)", {top})

    if systemish_top:
        name = f"{slug} profile backup"
        box.add_box(f"sys:{slug}", name,
                    "system-image layout at drive root: " +
                    ", ".join(sorted(systemish_top)), systemish_top)

    # standalone backup images: one box per image file
    for parts, ext in image_files:
        stem = os.path.splitext(parts[-1])[0]
        box.add_box(f"img:{'/'.join(parts).casefold()}",
                    stem or parts[-1],
                    f"backup image file (.{ext})", {"/".join(parts)})

    box.finalize()
    if box.boxes:
        logger.info("%s: detected %d archive box(es): %s", root,
                    len(box.boxes),
                    ", ".join(b["name"] for b in box.boxes.values()))
    return box


JUNK_WITHIN_BOX = re.compile(
    r"(^|[\\/])(appdata|history|filehistory|\$archive\$|temp|tmp|cache|"
    r"caches|cookies|recent|local settings)([\\/]|$)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Date / year / amount parsing
# ---------------------------------------------------------------------------

_DATE_YMD = re.compile(r"(?<!\d)(19[89]\d|20[0-3]\d)[-_. ]?(0[1-9]|1[0-2])"
                       r"[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)")
_DATE_MDY = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])[-_.](0?[1-9]|[12]\d|3[01])"
                       r"[-_.](19[89]\d|20[0-3]\d)(?!\d)")
_YEAR_SEG = re.compile(r"^(19[89]\d|20[0-3]\d)([ _-]|$)")
_AMOUNT = re.compile(r"\$ ?([\d,]{1,10}(?:\.\d{2})?)|"
                     r"(?<![\d.])(\d{1,6}\.\d{2}) ?(?:usd|dollars)",
                     re.IGNORECASE)


def parse_date_from_name(name):
    """Return (YYYY-MM-DD, evidence) or (None, None)."""
    m = _DATE_YMD.search(name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "date in filename"
    m = _DATE_MDY.search(name)
    if m:
        return (f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}",
                "US-style date in filename")
    return None, None


def parse_year(parts, name, modified_utc):
    """Return (year, source) where source in filename|path|mtime|None."""
    date, _ = parse_date_from_name(name)
    if date:
        return date[:4], "filename"
    for seg in parts[:-1]:
        m = _YEAR_SEG.match(seg.strip())
        if m:
            return m.group(1), "path"
        m = re.fullmatch(r".*\b(19[89]\d|20[0-3]\d)\b.*", seg)
        if m:
            return m.group(1), "path"
    if modified_utc[:4].isdigit():
        return modified_utc[:4], "mtime"
    return None, None


def parse_amount(name):
    m = _AMOUNT.search(name)
    if not m:
        return None
    return (m.group(1) or m.group(2)).replace(",", "")


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_component(s):
    s = _ILLEGAL.sub("-", s).strip(" .")
    return re.sub(r"\s+", " ", s)


# ---------------------------------------------------------------------------
# Media helpers
# ---------------------------------------------------------------------------

GENERIC_MEDIA_DIRS = {
    "raw", "footage", "video", "videos", "photo", "photos", "pictures",
    "images", "stills", "audio", "sound", "music", "dcim", "clips", "media",
    "exports", "export", "selects", "proxies", "proxy", "bts", "cards",
    "card1", "card2", "a-cam", "b-cam", "drone", "gopro", "misc", "new folder",
    "untitled", "assets", "files", "data", "backup", "old", "sorted",
    "unsorted", "to sort", "stuff",
}
_CARD_DIR = re.compile(r"^(100|101|102)[a-z0-9_]+$|^(dcim|private|avchd|"
                       r"clip|sub|ccm|xdroot|m4root)$", re.IGNORECASE)

FASTWORK_MAP = [
    (re.compile(r"(^|[\\/])(raw|footage|rushes|cards?|dcim|a-?cam|b-?cam|"
                r"drone|gopro|audio|sound)([\\/]|$)", re.I), "01_RAW"),
    (re.compile(r"(^|[\\/])(selects?|picks|keepers|circle ?takes)([\\/]|$)",
                re.I), "02_SELECTS"),
    (re.compile(r"(^|[\\/])(edit|edits|project|projects|premiere|resolve|"
                r"timeline|work)([\\/]|$)", re.I), "03_EDIT"),
    (re.compile(r"(^|[\\/])(exports?|final|finals|deliver(y|ables)?|master|"
                r"masters|output|uploads?)([\\/]|$)", re.I), "04_DELIVERABLES"),
]


def project_from_parts(parts):
    """Nearest non-generic ancestor dir; '' if file is loose at root."""
    for seg in reversed(parts[:-1]):
        low = seg.casefold()
        if low in GENERIC_MEDIA_DIRS or _CARD_DIR.match(seg):
            continue
        if re.fullmatch(r"(19[89]\d|20[0-3]\d)", seg.strip()):
            continue  # pure year folder; "2023 Acme Rebrand" stays a project
        return seg
    return ""


def fastwork_subfolder(rel_within_project, ext):
    for pat, folder in FASTWORK_MAP:
        if pat.search(rel_within_project):
            return folder, f"path segment matches {folder}"
    if ext in PROJECT_EXT:
        return "03_EDIT", "project-file extension"
    if ext in RAW_PHOTO_EXT or ext in {"braw", "r3d", "mts", "m2ts", "crm"}:
        return "01_RAW", "camera-original extension"
    if ext in VIDEO_EXT | PHOTO_EXT | AUDIO_EXT:
        return "01_RAW", "media extension, no structural hint (defaulted)"
    return "03_EDIT", "unmapped (defaulted)"


# ---------------------------------------------------------------------------
# Records helpers
# ---------------------------------------------------------------------------

RECORD_RULES = [
    ("Vehicles", re.compile(
        r"(vehicle|vin\b|dmv|registration|smog|carfax|auto ?insurance|"
        r"oil ?change|tire|mechanic|toyota|honda|ford|chevy|subaru|lexus)",
        re.I)),
    ("Business/Taxes", re.compile(
        r"(tax(es)?\b|irs\b|1099|w-?2\b|w-?9\b|schedule ?c|1040|ein\b|"
        r"quarterly)", re.I)),
    ("Business/Invoices", re.compile(r"(invoice|inv[ _-]?\d{2,})", re.I)),
    ("Business/Expenses", re.compile(
        r"(receipt|expense|reimburs)", re.I)),
    ("Business/Company", re.compile(
        r"(llc\b|operating agreement|articles of (org|inc)|business license|"
        r"dba\b|insurance cert|coi\b)", re.I)),
    ("Business", re.compile(
        r"(client|contract|proposal|estimate|quote|sow\b|agreement|deposit)",
        re.I)),
    ("Finance", re.compile(
        r"(statement|bank|checking|savings|401k|ira\b|brokerage|loan|"
        r"credit ?card|mortgage payoff|paypal|venmo)", re.I)),
    ("Home", re.compile(
        r"(mortgage|lease|rent\b|hoa\b|utility|utilities|repair|contractor|"
        r"appliance|warranty|escrow|deed|property)", re.I)),
]


def classify_record(cfg, parts, name, date, year):
    """Return (subfolder_path, who, evidence)."""
    hay = " ".join(parts).casefold() + " " + name.casefold()
    who = ""
    for code, cname in cfg["client_codes"].items():
        if code.casefold() in hay or cname.casefold() in hay:
            return (f"Records\\Business\\Clients\\{code} {cname}", cname,
                    f"matched client {code}")
    for sub, pat in RECORD_RULES:
        m = pat.search(hay)
        if m:
            folder = "Records\\" + sub.replace("/", "\\")
            if sub == "Business/Taxes":
                folder += f"\\{year}" if year else ""
            return folder, who, f"keyword {m.group(0)!r}"
    return "Records\\_Inbox", who, "no category keyword; routed to _Inbox"


def propose_record_name(name, ext, date, who, parts):
    """Build 'YYYY-MM-DD  what - who - $amount.ext' from available pieces."""
    stem = os.path.splitext(name)[0]
    amount = parse_amount(stem)
    what = _DATE_YMD.sub(" ", stem)
    what = _DATE_MDY.sub(" ", what)
    what = _AMOUNT.sub(" ", what)
    what = re.sub(r"[_]+", " ", what)
    what = sanitize_component(re.sub(r"\s{2,}", " ", what)).strip(" -")
    if not what:
        what = "document"
    if not who:
        parent = parts[-2] if len(parts) >= 2 else ""
        if parent and parent.casefold() not in GENERIC_MEDIA_DIRS:
            who = sanitize_component(parent)
    pieces = [what]
    if who and who.casefold() not in what.casefold():
        pieces.append(who)
    if amount:
        pieces.append(f"${amount}")
    return f"{date}  {' - '.join(pieces)}.{ext}" if ext else \
        f"{date}  {' - '.join(pieces)}"


# ---------------------------------------------------------------------------
# Main classification pass
# ---------------------------------------------------------------------------

def classify_paths(cfg, root):
    slug = drive_slug(root)
    return os.path.join(cfg["output_dir"], "classify",
                        f"classify-{slug}.csv")


def detect_repos(root, rows):
    """Rel-part tuples of directories that contain a .git dir.

    Accepts any iterable of inventory rows (single pass).
    """
    repos = set()
    for row in rows:
        parts = _split_rel(root, row["path"])
        for i, seg in enumerate(parts[:-1]):
            if seg.casefold() == ".git":
                repos.add(tuple(parts[:i]))
                break
    return repos


def _repo_root_for(parts, repo_roots):
    for i in range(len(parts)):
        if tuple(parts[:i]) in repo_roots:
            return "\\".join(parts[:i])
    return None


def run_classify(cfg, roots, dref, logger):
    """Classify all drives. Rewrites classify CSVs (cheap, pure computation).

    All inventory reads stream from the CSVs; memory holds only the hash
    candidates and dupe maps, never full inventories.
    """
    hashes = load_all_hashes(cfg, roots)

    dupe_input = []
    for root in roots:
        for row in iter_inventory(cfg, root):
            h = hashes.get(norm_key(row["path"]))
            if h and h["full"]:
                dupe_input.append({"path": row["path"], "size": h["size"],
                                   "mtime": row["modified_utc"],
                                   "full": h["full"]})
    d_dupes, ext_dupes, keepers = resolve_dupe_groups(dupe_input, dref)
    del dupe_input, hashes
    probable_d = probable_d_matches(
        cfg, roots, dref, lambda r: iter_inventory(cfg, r))
    write_d_hash_request(cfg, probable_d, logger)
    logger.info("dupes: %d exact-vs-D, %d external non-keepers, "
                "%d keeper groups, %d probable-vs-D",
                len(d_dupes), len(ext_dupes), len(keepers), len(probable_d))

    stats = {}
    for root in roots:
        box_map = detect_boxes(root, iter_inventory(cfg, root), logger)
        repo_roots = detect_repos(root, iter_inventory(cfg, root))
        out_path = classify_paths(cfg, root)
        if os.path.exists(out_path):
            os.remove(out_path)  # classification output only, never user data
        counts = {}
        with CsvAppender(out_path, CLASSIFY_COLUMNS) as out:
            for row in iter_inventory(cfg, root):
                rec = _classify_row(cfg, root, row, box_map, repo_roots,
                                    d_dupes, ext_dupes, keepers, probable_d)
                out.write(rec)
                counts[rec["class"]] = counts.get(rec["class"], 0) + 1
        stats[root] = counts
        logger.info("%s classified: %s", root, counts)
    return stats


def _classify_row(cfg, root, row, box_map, repo_roots, d_dupes, ext_dupes,
                  keepers, probable_d):
    parts = _split_rel(root, row["path"])
    name = parts[-1] if parts else os.path.basename(row["path"])
    ext = row["ext"]
    key = norm_key(row["path"])
    size = int(row["size"]) if row["size"] else 0

    rec = {c: "" for c in CLASSIFY_COLUMNS}
    rec.update({"path": row["path"], "size": row["size"], "drive": root,
                "confidence": "high", "nas_tier": "none"})

    def done(cls, subclass, evidence, confidence=None, proposed_path="",
             proposed_name="", nas_tier=None, dupe_of=""):
        rec["class"] = cls
        rec["subclass"] = subclass
        rec["evidence"] = evidence
        rec["proposed_path"] = proposed_path
        rec["proposed_name"] = proposed_name
        rec["dupe_of"] = dupe_of
        if confidence:
            rec["confidence"] = confidence
        if nas_tier:
            rec["nas_tier"] = nas_tier
        return rec

    if row["error"]:
        return done("UNKNOWN", "stat-error",
                    f"could not stat: {row['error']}", "low")

    # ----- archive box membership ------------------------------------------
    box_key = box_map.lookup(parts) if parts else None
    if box_key:
        box = box_map.boxes[box_key]
        box_name = sanitize_component(box["name"])
        rel = "\\".join(parts)
        note = ""
        if JUNK_WITHIN_BOX.search(rel):
            if key in d_dupes or key in ext_dupes or _is_junk(
                    parts, name, ext, size)[0]:
                note = "; junk-within-box (prune candidate, separate approval)"
            else:
                note = ("; inside version-store/AppData but NOT proven "
                        "duplicated elsewhere - potential sole survivor, "
                        "kept in box")
        elif (ext in MEDIA_EXT or ext in DOC_EXT) and \
                key not in d_dupes and key not in ext_dupes:
            note = "; sole-surviving content inside box (no dupe elsewhere)"
        return done(
            "ARCHIVE_BOX", box_name,
            f"member of archive box {box_name!r}: {box['evidence']}{note}",
            "high",
            "Archive\\" + box_name + "\\" + rel,
            "", "hdd-mirror")

    # ----- zero-byte --------------------------------------------------------
    if size == 0:
        return done("JUNK", "zero-byte", "zero-byte file", "high")

    # ----- exact dupes ------------------------------------------------------
    if key in d_dupes:
        return done("EXACT_DUPE_OF_D", "exact-sha256",
                    "SHA256 identical to D: reference copy "
                    "(safe-delete candidate after your approval)",
                    "high", dupe_of=d_dupes[key])
    if key in ext_dupes:
        return done("DUPE_EXTERNAL", "exact-sha256",
                    "SHA256 identical to elected keeper copy "
                    "(keep-one candidate)",
                    "high", dupe_of=ext_dupes[key])

    keeper_note = ""
    if key in keepers:
        keeper_note = (f" [elected keeper of {keepers[key]}-copy duplicate "
                       f"group]")
    probable_note = ""
    if key in probable_d:
        probable_note = (f" [PROBABLE dupe of D: {probable_d[key]} by "
                         f"size+name; D: reference lacks hashes - see "
                         f"d-hash-request.csv]")

    # ----- junk -------------------------------------------------------------
    is_junk, junk_kind, junk_evidence = _is_junk(parts, name, ext, size)
    if is_junk:
        conf = "high" if not probable_note else "medium"
        return done("JUNK", junk_kind, junk_evidence + keeper_note +
                    probable_note, conf)

    # ----- git repos: hands off, one decision per repo ---------------------
    repo = _repo_root_for(parts, repo_roots)
    if repo is not None:
        return done("UNKNOWN", "git-repo",
                    f"inside git repository {repo or root}; "
                    f"repos need a per-repo decision" + probable_note,
                    "medium")

    # ----- media ------------------------------------------------------------
    if ext in MEDIA_EXT and not (
            ext in {"jpg", "jpeg", "png", "pdf"} and
            SCANNED_RECORD_HINTS.search(name)):
        return _classify_media(cfg, rec, done, parts, name, ext, row,
                               keeper_note, probable_note)

    # ----- records ----------------------------------------------------------
    if ext in DOC_EXT or (ext in {"jpg", "jpeg", "png"} and
                          SCANNED_RECORD_HINTS.search(name)):
        return _classify_records(cfg, rec, done, parts, name, ext, row,
                                 keeper_note, probable_note)

    return done("UNKNOWN", f"ext-{ext or 'none'}",
                f"unrecognized type .{ext or '(no extension)'} in "
                f"{'/'.join(parts[:-1]) or 'drive root'}" +
                keeper_note + probable_note, "low")


def _is_junk(parts, name, ext, size):
    low = name.casefold()
    if low in JUNK_NAMES:
        return True, "os-litter", f"OS litter filename {name!r}"
    if low.startswith("~$") or low.startswith("._"):
        return True, "temp", f"temp/office-lock filename pattern {name!r}"
    if ext in JUNK_EXT:
        return True, "temp", f"temporary-file extension .{ext}"
    for seg in parts[:-1]:
        if seg.casefold() in CACHE_DIRS:
            return True, "cache", \
                f"inside cache/regenerable directory {seg!r}"
    if ext in INSTALLER_EXT:
        m = INSTALLER_NAME.search(name)
        parent_hit = next((s for s in parts[:-1]
                           if s.casefold() in INSTALLER_DIRS), None)
        if m and parent_hit:
            return True, "installer", \
                (f"installer: name pattern {m.group(0)!r} inside "
                 f"{parent_hit!r} directory")
        if m:
            return True, "installer", f"installer name pattern {m.group(0)!r}"
    return False, "", ""


def _classify_media(cfg, rec, done, parts, name, ext, row, keeper_note,
                    probable_note):
    year, year_src = parse_year(parts, name, row["modified_utc"])
    project = project_from_parts(parts)
    hay = ("/".join(parts)).casefold()
    personal = next((k for k in cfg["personal_shoot_keywords"]
                     if k.casefold() in hay), None)

    conf = "high"
    ev = []
    if year_src == "filename":
        ev.append(f"year {year} from filename date")
    elif year_src == "path":
        ev.append(f"year {year} from path segment")
    elif year_src == "mtime":
        ev.append(f"year {year} from file mtime (no date in path/name)")
        conf = "medium"
    else:
        conf = "low"
        ev.append("no year derivable")
    if not project:
        project = "_loose files"
        conf = "low"
        ev.append("no project folder derivable (loose file)")
    else:
        ev.append(f"project {project!r} from path")

    project_c = sanitize_component(project)
    idx = next((i for i, s in enumerate(parts) if s == project), None)
    rel_within = "\\".join(parts[idx + 1:]) if idx is not None else name

    if personal:
        proposed = f"Media\\Personal Shoots\\{project_c}\\{rel_within}"
        ev.append(f"personal shoot (keyword {personal!r})")
        tier = "hdd-mirror"
        sub = "personal-shoot"
    else:
        mtime = row["modified_utc"]
        cutoff = cfg.get("_activity_cutoff_iso", "")
        active = bool(cutoff and mtime and mtime >= cutoff)
        if active:
            folder, map_ev = fastwork_subfolder(
                "\\".join(parts[:-1]), ext)
            proposed = f"{project_c}\\{folder}\\{name}"
            ev.append(f"active project (modified {mtime[:10]}); "
                      f"fastwork mapping: {map_ev}")
            if "defaulted" in map_ev:
                conf = "medium" if conf == "high" else conf
            tier = "fastwork"
            sub = "client-or-project"
        else:
            proposed = (f"Media\\{year}\\{project_c}\\{rel_within}"
                        if year else f"Media\\_unknown-year\\{project_c}"
                                     f"\\{rel_within}")
            tier = "hdd-mirror"
            sub = "client-or-project"
    if probable_note:
        conf = "low"
    return done("MEDIA", sub, "; ".join(ev) + keeper_note + probable_note,
                conf, proposed, "", tier)


def _classify_records(cfg, rec, done, parts, name, ext, row, keeper_note,
                      probable_note):
    date, date_ev = parse_date_from_name(name)
    conf = "high"
    if not date:
        date = row["modified_utc"][:10]
        date_ev = "file mtime (no date in filename)"
        conf = "medium"
    year = date[:4] if date else ""
    folder, who, cat_ev = classify_record(cfg, parts, name, date, year)
    if folder.endswith("_Inbox"):
        conf = "low"
    new_name = propose_record_name(name, ext, date, who, parts) if date else ""
    if probable_note:
        conf = "low"
    return done(
        "RECORDS",
        folder.split("\\")[1] if "\\" in folder else "records",
        f"document ({cat_ev}); date {date} from {date_ev}" +
        keeper_note + probable_note,
        conf, folder, new_name, "hdd-mirror")
