"""The plan stage: turn per-drive classifications into ONE verified,
ordered, collision-free execution plan.

Everything upstream of this file is analysis; everything downstream is the
future execution phase that copies to the NAS and, after approval, deletes
duplicates. This stage exists so that the executor never has to reason:
it replays rows in order, verifies each one against the hashes recorded
here, and halts on any mismatch. All safety is proven at plan time:

  * every row carries the SHA256 triage measured where one exists, so a
    copy is verified against what was actually catalogued, and a DELETE is
    never emitted without byte-certain proof that its keeper holds the
    identical content;
  * no two rows may target the same destination path. Two byte-identical
    sources are merged into one copy; two DIFFERENT files aimed at one
    destination are a violation that stops the whole plan - a copy phase
    must never silently overwrite;
  * order is a guarantee, not a convention: every delete row names the plan
    row of its keeper's copy in `depends_on`, and all copies precede all
    deletes, so a delete is unreachable until its keeper is copied AND
    verified;
  * a delete that cannot be proven safe is HELD, not emitted, and reported
    by reason - a delete that does not happen costs disk, never data;
  * a contradiction (classification says duplicate, recorded hashes differ)
    or a destination that still collides after qualification is fatal: the
    plan is not written at all, every offending row is listed in
    plan-violations.csv, and any previous plan is invalidated.

Every row also carries the volume signature its drive was inventoried
with, because all six externals mounted as F:: the executor must confirm
the right disk is present before acting on a row, since a path alone does
not identify a file in this fleet.

This stage is read-only against every drive: it reads only the CSVs the
runs already wrote, and writes only under <workspace>/_plan/.

Rows it will NOT plan (counted and reported, never silently dropped):
UNKNOWN/hold rows - they belong to the decision list, and planning them
would launder an unanswered question into an action - and any delete whose
proof is missing.
"""

import hashlib
import os
import re
from collections import Counter, defaultdict

from .util import (
    CLASSIFY_COLUMNS, HASH_COLUMNS, CsvRewriter, atomic_write_json, fmt_gb,
    load_json, norm_key, read_csv_rows, write_text,
)
from .crossdrive import _csvs, find_runs
from . import __version__

PLAN_DIR = "_plan"

# Windows strips a trailing dot or space from every path component and treats
# CON/PRN/... as devices whatever the extension. A destination carrying any
# of these does not name the file it appears to.
_RESERVED_WIN = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_WIN_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|\\\\)")

PLAN_COLUMNS = [
    "seq",            # execution order; the executor processes ascending
    "action",         # copy | delete-candidate
    "depends_on",     # for deletes: seq of the keeper's copy row, or D-REF
    "source_drive",   # run folder name (drive identity - letters repeat)
    "source_path",
    "size",
    "sha256",         # what triage measured; "" only where noted in verify
    "verify",         # sha256 | hash-at-copy | zero-byte
    "nas_tier",       # fastwork | hdd-mirror
    "dest_path",      # relative to the tier root; includes the final name
    "keeper_path",    # for deletes: the copy that survives
    "keeper_sha256",
    "class",
    "confidence",
    "source_volume",  # volume label+size recorded when this drive was
                      # inventoried; the executor must confirm it is what
                      # is mounted before touching any row for this drive
    "note",           # anything done to this row that a reader must know
]

VIOLATION_COLUMNS = ["kind", "detail", "source_drive", "source_path",
                     "other_drive", "other_path", "dest_path"]

HELD_COLUMNS = ["source_drive", "source_path", "size", "class", "reason"]

_COPY_CLASSES = {"MEDIA", "RECORDS", "ARCHIVE_BOX"}
_DELETE_CLASSES = {"JUNK", "EXACT_DUPE_OF_D", "DUPE_EXTERNAL"}


def _run_hashes(run_dir):
    """norm_key(path) -> full sha256 for one run.

    Last row per path wins INCLUDING error rows, matching what classify
    consumed: a later failed re-read supersedes an earlier good hash, so a
    file classify treated as unhashed is unhashed here too. Disagreeing
    would let a delete cite a hash the classification never saw.
    """
    out = {}
    for csv_path in (_csvs(run_dir, "hashes", "prefix-") +
                     _csvs(run_dir, "hashes", "full-")):
        for row in read_csv_rows(csv_path, HASH_COLUMNS):
            key = norm_key(row["path"])
            if row["error"] or not row["full_sha256"]:
                out.pop(key, None)
            else:
                out[key] = row["full_sha256"]
    return out


def run_volumes(run_dir):
    """slug -> volume signature 'LABEL (SIZE bytes)' for this run.

    Every drive in this fleet mounted as F:, so a path names a file only
    once you know WHICH disk is at that letter. `inventory` stamps the
    label and size beside each inventory; carrying it into the plan is what
    lets an executor refuse to act on the wrong drive. Keyed per slug
    because one run folder can hold several drives - joining them into one
    string would stamp every row with a signature naming disks it is not on,
    and the executor's first rule is to match that signature to what is
    actually mounted.
    """
    sigs = {}
    d = os.path.join(run_dir, "inventory")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.startswith("inventory-") and f.endswith(".meta.json"):
                meta = load_json(os.path.join(d, f)) or {}
                if meta.get("label") is not None:
                    slug = f[len("inventory-"):-len(".meta.json")]
                    sigs[slug] = (f"{meta.get('label')} "
                                  f"({meta.get('size')} bytes)")
    return sigs


def _iter_classified(run_dir):
    """Yield (slug, row) so a row can be tied back to the DRIVE it came
    from - a run folder may hold more than one, and they are different
    physical disks that happened to share a letter."""
    for csv_path in _csvs(run_dir, "classify", "classify-"):
        slug = os.path.basename(csv_path)[len("classify-"):-len(".csv")]
        for row in read_csv_rows(csv_path, CLASSIFY_COLUMNS):
            yield slug, row


def _basename(path):
    r"""The final component of a Windows-style path, regardless of the OS
    this runs on - os.path.basename would keep the whole F:\ path intact
    on a non-Windows machine and quietly disable collision detection."""
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def _dest_of(row):
    """Destination path relative to the tier root, final filename included."""
    folder = (row["proposed_path"] or "").strip("\\/")
    name = row["proposed_name"] or _basename(row["path"])
    return (folder + "\\" + name) if folder else name


def dest_key(tier, dest):
    r"""The identity of a destination FILE, not of the string naming it.

    Two spellings Windows resolves to one file must collide here, or the
    "no two rows target the same destination" guarantee is enforced only
    against textually identical paths: '/' and '\' are both separators,
    repeats collapse, and a trailing dot or space on a component is dropped.
    """
    parts = [p.rstrip(". ") for p in re.split(r"[\\/]+", dest) if p]
    return (tier.strip().casefold(), "\\".join(parts).casefold())


def dest_problem(dest):
    """Why this destination may not be written, or None.

    The executor is specified as dumb - it creates parent directories and
    copies - so a destination that walks out of its tier root is a real
    write outside the approved area. This is the stage that has to say no.
    """
    if not dest.strip():
        return "empty destination"
    if _WIN_ABSOLUTE.match(dest.strip()):
        return ("destination is an absolute path or UNC share, so it does "
                "not land under the tier root")
    parts = re.split(r"[\\/]+", dest)
    for p in parts:
        if p in ("..", "."):
            return (f"destination contains a {p!r} component and can walk "
                    f"outside the tier root")
        stem = p.split(".")[0].strip().casefold()
        if stem in _RESERVED_WIN:
            return (f"destination component {p!r} is a reserved Windows "
                    f"device name")
    if not [p for p in parts if p.strip(". ")]:
        return "destination has no usable component"
    return None


def _qualified_dests(dest, drive, source_path):
    r"""Destinations to try, in order, when `dest` is already claimed.

    Qualifying by drive alone cannot separate two files from the SAME drive
    - the prefix is identical - so a third same-drive clash used to abort
    the whole fleet's plan. The final form is keyed on the source path, so
    it is unique by construction and deterministic across builds.
    """
    yield drive + "\\" + dest
    folder, _, name = dest.rpartition("\\")
    stem, dot, ext = name.rpartition(".")
    tag = hashlib.sha1(norm_key(source_path).encode("utf-8",
                                                    "surrogatepass")
                       ).hexdigest()[:8]
    tagged = (f"{stem} [{tag}]{dot}{ext}" if dot else f"{name} [{tag}]")
    yield (folder + "\\" + tagged) if folder else tagged
    yield drive + "\\" + ((folder + "\\" + tagged) if folder else tagged)


def build(workspace, logger):
    """Assemble and verify the plan. Returns a summary dict, or raises
    SystemExit - after writing plan-violations.csv - when the plan cannot
    be proven safe."""
    runs = [(n, d) for n, d in find_runs(workspace)
            if _csvs(d, "classify", "classify-")]
    if not runs:
        raise SystemExit(
            f"no classified runs under {workspace}; run the per-drive "
            f"triage first (Triage a Drive.bat).")
    logger.info("planning over %d classified runs: %s", len(runs),
                ", ".join(n for n, _ in runs))

    out_dir = os.path.join(workspace, PLAN_DIR)
    os.makedirs(out_dir, exist_ok=True)
    plan_csv = os.path.join(out_dir, "plan.csv")
    violations = []

    def violate(kind, detail, drive, path, other_drive="", other_path="",
                dest=""):
        violations.append({
            "kind": kind, "detail": detail, "source_drive": drive,
            "source_path": path, "other_drive": other_drive,
            "other_path": other_path, "dest_path": dest})

    # The previous plan is invalidated HERE, before a single row is read.
    # It described inputs that no longer hold; from this point until a new
    # one is proven, there is nothing anyone may execute. Doing it at the
    # end of the violation branch instead left the disproven plan.csv whole
    # whenever the build died on the way - a locked CSV, a Ctrl-C, a bad
    # header, a non-numeric size - and every one of those exits reports
    # failure while an executable plan sits on disk.
    if os.path.exists(plan_csv):
        with CsvRewriter(plan_csv, PLAN_COLUMNS):
            pass
    atomic_write_json(os.path.join(out_dir, "plan-info.json"),
                      {"state": "BUILDING - no plan is valid right now"})
    write_text(os.path.join(out_dir, "plan-report.md"), "\n".join([
        "# Execution plan - NOT BUILT", "",
        "A build is in progress or did not finish. There is nothing here "
        "to execute.", ""]))

    # ---- gather every actionable row, with its measured hash -------------
    # Only the fields the plan needs are kept: at fleet scale the full row
    # dicts would be several GB resident.
    copies, deletes = [], []
    held = defaultdict(int)
    held_bytes = 0
    hashes_by_run = {}
    volumes = {}
    contributing = set()
    for name, run_dir in runs:
        hashes_by_run[name] = _run_hashes(run_dir)
        volumes[name] = run_volumes(run_dir)
        default_vol = " | ".join(v for _s, v in sorted(volumes[name].items()))
        for slug, row in _iter_classified(run_dir):
            contributing.add(name)
            vol = volumes[name].get(slug, default_vol)
            cls = row["class"]
            if cls in _COPY_CLASSES:
                copies.append((name, row["path"], row["size"],
                               _dest_of(row), row["nas_tier"] or "hdd-mirror",
                               bool(row["proposed_path"]), cls,
                               row["confidence"], vol))
            elif cls in _DELETE_CLASSES:
                deletes.append((name, row["path"], row["size"], cls,
                                row["dupe_of"], row["confidence"], vol))
            else:
                held[cls or "(blank)"] += 1
                if row["size"]:
                    held_bytes += int(row["size"])

    # ---- the fleet must have been classified by ONE set of rules ---------
    # reclassify refuses to report success on a half-updated fleet, but
    # nothing stopped a user from building the plan anyway. A plan that
    # mixes rule sets is not one decision, it is several, and which files
    # got which is invisible in the output.
    provenance = {}
    for name, run_dir in runs:
        provenance[name] = load_json(
            os.path.join(run_dir, "run-info.json")) or \
            {"note": "unrecorded (classified before provenance existed)"}
    # Only folders that actually contribute a row can put mixed rules into
    # the plan. A drive that held no files still has a header-only classify
    # CSV and whatever run-info it was left with - re-classify skips it,
    # correctly, so its provenance goes stale and means nothing.
    for field, label in (("activity_cutoff_iso", "activity cutoff"),
                         ("tool_version", "tool version")):
        seen = defaultdict(list)
        for name, info in provenance.items():
            if name in contributing:
                seen[info.get(field) or "(unrecorded)"].append(name)
        if len(seen) > 1:
            detail = "; ".join(
                f"{v}: {', '.join(sorted(ns))}"
                for v, ns in sorted(seen.items()))
            violate("mixed-provenance",
                    f"run folders disagree about the {label} they were "
                    f"classified with ({detail})", "", "")

    # ---- pass 1: copies. Every destination is unique or the plan stops ---
    copies.sort(key=lambda t: (t[0], t[1].casefold()))
    plan_rows = []
    seq = 0
    dest_map = {}    # (tier, dest casefold) -> (sha, seq, drive, path)
    copy_seq = defaultdict(dict)  # run name -> norm_key(source) -> seq
    merged = qualified = unhashed_copies = 0
    for name, path, size, dest, tier, has_dest, cls, conf, vol in copies:
        if not has_dest:
            violate("no-destination", f"{cls} row has no proposed_path",
                    name, path)
            continue
        bad = dest_problem(dest)
        if bad:
            violate("unsafe-destination", bad, name, path, "", "", dest)
            continue
        sha = hashes_by_run[name].get(norm_key(path), "")
        key = dest_key(tier, dest)
        prior = dest_map.get(key)
        note = ""
        if prior is not None:
            p_sha, p_seq, p_drive, p_path = prior
            if sha and p_sha and sha == p_sha:
                # byte-identical content aimed at one destination: one copy
                # suffices, and anything depending on this source can depend
                # on the surviving row instead
                merged += 1
                copy_seq[name][norm_key(path)] = p_seq
                continue
            # Different (or unprovable) content. Drives are scanned one at a
            # time, so classification cannot know another drive holds a
            # same-named project - the clash only becomes visible here.
            # Overwriting is never an option, so the destination is moved.
            # The drive name alone cannot separate two files from the SAME
            # drive, which is how a third same-drive clash used to abort the
            # entire fleet's plan; the source-path tag always can.
            for cand in _qualified_dests(dest, name, path):
                cand_key = dest_key(tier, cand)
                if cand_key not in dest_map:
                    dest, key = cand, cand_key
                    break
            else:
                q_sha, _q_seq, q_drive, q_path = dest_map[key]
                violate("destination-collision",
                        "two files still collide after every attempt to "
                        "qualify the destination",
                        name, path, q_drive, q_path, dest)
                continue
            qualified += 1
            note = (f"destination qualified: {p_drive} already claims "
                    f"{p_path}" if p_drive != name else
                    f"destination qualified: {p_path} on this same drive "
                    f"already claims that path")
        seq += 1
        dest_map[key] = (sha, seq, name, path)
        copy_seq[name][norm_key(path)] = seq
        if not sha:
            unhashed_copies += 1
        plan_rows.append({
            "seq": seq, "action": "copy", "depends_on": "",
            "source_drive": name, "source_path": path,
            "size": size, "sha256": sha,
            "verify": "sha256" if sha else "hash-at-copy",
            "nas_tier": tier, "dest_path": dest,
            "keeper_path": "", "keeper_sha256": "",
            "class": cls, "confidence": conf,
            "source_volume": vol, "note": note,
        })

    # ---- pass 2: deletes. Provable, or not planned at all ----------------
    # "Not planned" is always safe - a delete that does not happen costs
    # disk, never data - so an unprovable delete is HELD and reported, not
    # a violation. Only a contradiction (classification says duplicate, the
    # recorded hashes disagree) is fatal: that means something upstream is
    # wrong and no delete in this plan can be trusted.
    deletes.sort(key=lambda t: (t[0], t[1].casefold()))
    held_deletes = defaultdict(int)
    held_delete_bytes = 0

    held_rows = []

    def hold_delete(reason, size, drive="", path="", cls=""):
        nonlocal held_delete_bytes
        held_deletes[reason] += 1
        held_delete_bytes += size
        held_rows.append({"source_drive": drive, "source_path": path,
                          "size": size, "class": cls, "reason": reason})

    for name, path, size_s, cls, dupe_of, conf, vol in deletes:
        sha = hashes_by_run[name].get(norm_key(path), "")
        size = int(size_s) if size_s else 0
        rec = {
            "seq": 0, "action": "delete-candidate", "depends_on": "",
            "source_drive": name, "source_path": path,
            "size": size_s, "sha256": sha, "verify": "sha256",
            "nas_tier": "", "dest_path": "",
            "keeper_path": dupe_of, "keeper_sha256": "",
            "class": cls, "confidence": conf,
            "source_volume": vol, "note": "",
        }
        if cls == "DUPE_EXTERNAL":
            # the keeper lives on the same drive (dupe groups are per-run);
            # it must be scheduled as a copy, and both hashes must be
            # present and identical - byte-certainty is the only licence
            keeper_sha = hashes_by_run[name].get(norm_key(dupe_of), "")
            kseq = copy_seq[name].get(norm_key(dupe_of))
            if sha and keeper_sha and sha != keeper_sha:
                violate("hash-contradiction",
                        "classification calls these duplicates but their "
                        "recorded SHA256 values DIFFER", name, path, name,
                        dupe_of)
                continue
            if not sha or not keeper_sha:
                hold_delete("duplicate or its keeper has no measured "
                            "SHA256 (close the coverage gap first)", size,
                            name, path, cls)
                continue
            if kseq is None:
                hold_delete("the keeper is not scheduled to be copied, so "
                            "this delete cannot be ordered after it", size,
                            name, path, cls)
                continue
            rec["depends_on"] = kseq
            rec["keeper_sha256"] = keeper_sha
        elif cls == "EXACT_DUPE_OF_D":
            if not sha:
                hold_delete("no measured SHA256 for a dupe-of-D row", size,
                            name, path, cls)
                continue
            # The keeper is on D:, which this tool never reads, so there is
            # no independently recorded hash to compare against: keeper_sha
            # below is the value the executor must FIND at keeper_path, not
            # a second measurement. That makes naming the keeper the only
            # check available here - and without it the row would instruct
            # a delete whose stated proof is on a path that is empty.
            if not dupe_of or norm_key(dupe_of) == norm_key(path):
                hold_delete("classified as a copy of a D: file but no "
                            "distinct D: path was recorded, so the keeper "
                            "cannot be re-verified", size, name, path, cls)
                continue
            rec["depends_on"] = "D-REF"
            rec["keeper_sha256"] = sha
            rec["note"] = ("keeper_sha256 is the value the executor must "
                           "find at keeper_path on D:, not a second "
                           "measurement taken here")
        else:  # JUNK
            if size == 0:
                rec["verify"] = "zero-byte"
            elif sha:
                rec["verify"] = "sha256"
            else:
                # Six drives all mount as F:, so a path is not an identity.
                # Deleting a non-empty file the tool never read, on nothing
                # but its path, is exactly the unrecoverable mistake this
                # stage exists to prevent.
                hold_delete("junk with no measured SHA256 - a non-empty "
                            "file is never deleted on its path alone", size,
                            name, path, cls)
                continue
        seq += 1
        rec["seq"] = seq
        plan_rows.append(rec)

    # ---- held deletes are named, not just counted ------------------------
    # "Held and explained" is a guarantee; an aggregate count cannot be
    # checked, re-verified or argued with.
    with CsvRewriter(os.path.join(out_dir, "plan-held.csv"),
                     HELD_COLUMNS) as w:
        for r in sorted(held_rows, key=lambda r: (r["source_drive"],
                                                  r["source_path"])):
            w.write(r)

    # ---- violations stop everything --------------------------------------
    if violations:
        vio_csv = os.path.join(out_dir, "plan-violations.csv")
        with CsvRewriter(vio_csv, VIOLATION_COLUMNS) as w:
            for v in violations:
                w.write(v)
        atomic_write_json(os.path.join(out_dir, "plan-info.json"),
                          {"state": "VIOLATIONS - NO PLAN",
                           "violations": len(violations)})
        # plan.csv was already blanked before the build started, so there is
        # nothing executable to leave behind at this point.
        write_text(os.path.join(out_dir, "plan-report.md"), "\n".join([
            "# Execution plan - NOT BUILT", "",
            f"{len(violations):,} row(s) could not be proven safe, so no "
            f"plan was written. There is nothing here to execute.", "",
            "Every problem row is listed in `plan-violations.csv`.", ""]))
        by_kind = Counter(v["kind"] for v in violations)
        # The remedy differs completely by kind, and naming the wrong one
        # sends the user off to re-hash drives that were never the problem.
        hints = {
            "hash-contradiction":
                "A hash contradiction means a file is classified as a "
                "duplicate but the recorded SHA256s differ. Re-run "
                "Re-Classify All Drives.bat; if it survives that, the two "
                "hashes were taken at different times and the file changed "
                "in between - re-hash that drive.",
            "destination-collision":
                "A destination collision means two DIFFERENT files are "
                "aimed at one path, so a copy would overwrite. Open the CSV "
                "and read source_path against other_path: they are usually "
                "application or system files that should never have been "
                "proposed as your own documents. Nothing needs re-hashing.",
            "no-destination":
                "A row with no destination is a classification that decided "
                "to move a file but never said where. Re-run Re-Classify "
                "All Drives.bat; if it survives, the row is named in the "
                "CSV and needs a rule fix, not a re-scan.",
        }
        raise SystemExit(
            f"NO PLAN WRITTEN: {len(violations):,} row(s) cannot be proven "
            f"safe - " +
            ", ".join(f"{k} {n:,}" for k, n in by_kind.most_common()) +
            f". Every one is listed with its counterpart in {vio_csv}.\n\n" +
            "\n\n".join(hints[k] for k, _ in by_kind.most_common()
                        if k in hints))

    # ---- emit -------------------------------------------------------------
    with CsvRewriter(plan_csv, PLAN_COLUMNS) as w:
        for r in plan_rows:
            w.write(r)

    n_copy = sum(1 for r in plan_rows if r["action"] == "copy")
    n_del = len(plan_rows) - n_copy
    copy_bytes = sum(int(r["size"]) for r in plan_rows
                     if r["action"] == "copy" and r["size"])
    del_bytes = sum(int(r["size"]) for r in plan_rows
                    if r["action"] != "copy" and r["size"])

    # A plan's identity is its content. seq numbers are positional, so a
    # rebuild after new hashes arrive renumbers everything; an executor that
    # recorded "seq 42 done" against the previous build would otherwise
    # satisfy a different row's depends_on with it.
    plan_id = hashlib.sha256("\n".join(
        "\x1f".join(str(r[c]) for c in PLAN_COLUMNS) for r in plan_rows
    ).encode("utf-8", "surrogatepass")).hexdigest()[:16]

    info = {
        "plan_id": plan_id,
        "state": "PLAN WRITTEN",
        "tool_version": __version__,
        "workspace": workspace,
        "runs": provenance,
        "volumes": {n: volumes[n] for n, _ in runs},
        "rows": {"copy": n_copy, "delete_candidate": n_del,
                 "merged_identical": merged,
                 "destinations_qualified": qualified,
                 "held_not_planned": dict(held),
                 "deletes_held_unprovable": dict(held_deletes)},
        "bytes": {"copy": copy_bytes, "delete_candidate": del_bytes,
                  "held": held_bytes,
                  "deletes_held": held_delete_bytes},
        "copies_without_measured_hash": unhashed_copies,
        "deletes_held_rows": len(held_rows),
    }
    atomic_write_json(os.path.join(out_dir, "plan-info.json"), info)
    stale_vio = os.path.join(out_dir, "plan-violations.csv")
    if os.path.exists(stale_vio):
        with CsvRewriter(stale_vio, VIOLATION_COLUMNS):
            pass  # header-only: the violations it listed no longer exist

    report = os.path.join(out_dir, "plan-report.md")
    write_text(report, "\n".join([
        "# Execution plan",
        "",
        f"Built by drive-triage v{__version__} over {len(runs)} classified "
        f"runs: " + ", ".join(n for n, _ in runs),
        "",
        f"**Plan id `{plan_id}`.** `seq` numbers are positions in THIS "
        f"build and are renumbered by the next one. An executor must record "
        f"the plan id alongside every completed seq and refuse to treat a "
        f"success recorded under a different plan id as satisfying a "
        f"`depends_on` here.",
        "",
        "Nothing here has been executed. This file and plan.csv are the "
        "complete input for a future, separately approved execution "
        "session.",
        "",
        "## Contents",
        "",
        f"- **{n_copy:,} copies** ({fmt_gb(copy_bytes)}) - every MEDIA, "
        f"RECORDS and ARCHIVE_BOX file, ordered first",
        f"- **{n_del:,} delete-candidates** ({fmt_gb(del_bytes)}) - ordered "
        f"strictly after all copies, every one carrying byte-certain proof",
        f"- {merged:,} byte-identical sources merged into single copies",
        f"- {qualified:,} destinations moved aside because something else "
        f"already claimed that path - by source drive where that separates "
        f"them, otherwise by a tag derived from the source path (two files "
        f"on ONE drive share a drive name, so it cannot separate those)",
        "",
        "## Deliberately NOT planned",
        "",
        f"- {sum(held.values()):,} rows ({fmt_gb(held_bytes)}) classified "
        f"UNKNOWN/hold - they belong to the decision list, and planning "
        f"them would launder an unanswered question into an action: " +
        (", ".join(f"{k}={v:,}" for k, v in sorted(held.items())) or "none"),
        f"- {sum(held_deletes.values()):,} delete-candidates "
        f"({fmt_gb(held_delete_bytes)}) that could not be proven safe. A "
        f"delete that does not happen costs disk, never data, so these are "
        f"held rather than emitted:",
        "",
    ] + ([f"    - {n:,}: {reason}" for reason, n in
          sorted(held_deletes.items(), key=lambda kv: -kv[1])]
         or ["    - none"]) + [
        "",
        f"- Every held row above is named individually, with its reason, in "
        f"`plan-held.csv` ({len(held_rows):,} rows).",
        "",
        f"- {unhashed_copies:,} copy rows have no measured SHA256 (their "
        f"size never collided, so triage never read them). Copying is "
        f"non-destructive: the executor hashes them while reading and "
        f"verifies the destination against that.",
        f"- The only DELETE rows without a measured SHA256 are zero-byte "
        f"files, which carry `verify=zero-byte` and are proven by re-"
        f"stat'ing the size (rule 4). Every other delete without a hash is "
        f"held above, not emitted.",
        "",
        "## Rules the executor must follow (in order, no exceptions)",
        "",
        "0. Before touching ANY row, confirm the drive named by "
        "`source_drive` is the one mounted: its `source_volume` (label and "
        "size, recorded when that drive was inventoried) must match the "
        "volume actually present. Every drive in this fleet mounted as "
        "F:, so a path alone does not name a file. A blank "
        "`source_volume` means no signature was recorded - re-verify that "
        "drive by content before acting on its rows.",
        "1. Process rows in ascending `seq`. All copies precede all "
        "deletes by construction.",
        "2. A copy: create parent dirs; refuse to overwrite an existing "
        "destination unless its SHA256 already equals the row's; copy; "
        "re-hash the destination and require it to equal `sha256` (or the "
        "hash computed while reading the source, when `verify` is "
        "hash-at-copy). Record success per seq.",
        "3. A delete-candidate with a numeric `depends_on` may run ONLY "
        "when that seq has recorded success - the keeper is on the NAS and "
        "verified. `D-REF` means: re-hash the file at `keeper_path` on D: "
        "and require it to equal `keeper_sha256` first. An EMPTY "
        "`depends_on` occurs only on JUNK rows, which have no keeper.",
        "4. Before any delete, re-hash `source_path` and require it to "
        "equal `sha256`. The sole exception is `verify` = zero-byte: "
        "re-stat the file and require size 0 (a file that has since gained "
        "content is not the file this plan classified). No delete row "
        "exists without one of those two proofs.",
        "5. Any verification failure halts the run. Never skip, never "
        "guess.",
        "",
        "## Files",
        "",
        "- `plan.csv` - the plan, one row per action",
        "- `plan-info.json` - provenance: tool version, per-run "
        "classification records, recorded volume signatures, row and byte "
        "totals",
        "",
    ]))
    logger.info("plan: %d copies, %d delete-candidates, %d merged, "
                "%d qualified, %d held, %d deletes held unprovable",
                n_copy, n_del, merged, qualified, sum(held.values()),
                sum(held_deletes.values()))
    return {"plan_csv": plan_csv, "report": report, "copies": n_copy,
            "deletes": n_del, "merged": merged, "qualified": qualified,
            "held": sum(held.values()),
            "held_deletes": sum(held_deletes.values()),
            "held_delete_bytes": held_delete_bytes,
            "copy_bytes": copy_bytes, "delete_bytes": del_bytes,
            "unhashed_copies": unhashed_copies}
