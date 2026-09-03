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

import os
from collections import Counter, defaultdict

from .util import (
    CLASSIFY_COLUMNS, HASH_COLUMNS, CsvRewriter, atomic_write_json, fmt_gb,
    load_json, norm_key, read_csv_rows, write_text,
)
from .crossdrive import _csvs, find_runs
from . import __version__

PLAN_DIR = "_plan"

PLAN_COLUMNS = [
    "seq",            # execution order; the executor processes ascending
    "action",         # copy | delete-candidate
    "depends_on",     # for deletes: seq of the keeper's copy row, or D-REF
    "source_drive",   # run folder name (drive identity - letters repeat)
    "source_path",
    "size",
    "sha256",         # what triage measured; "" only where noted in verify
    "verify",         # sha256 | hash-at-copy | junk-no-keeper | zero-byte
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
    """Volume signatures this run recorded, as 'LABEL (SIZE bytes)'.

    Every drive in this fleet mounted as F:, so a path names a file only
    once you know WHICH disk is at that letter. `inventory` stamps the
    label and size beside each inventory; carrying it into the plan is what
    lets an executor refuse to act on the wrong drive.
    """
    sigs = []
    d = os.path.join(run_dir, "inventory")
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.startswith("inventory-") and f.endswith(".meta.json"):
                meta = load_json(os.path.join(d, f)) or {}
                if meta.get("label") is not None:
                    sigs.append(f"{meta.get('label')} "
                                f"({meta.get('size')} bytes)")
    return " | ".join(sigs)


def _iter_classified(run_dir):
    for csv_path in _csvs(run_dir, "classify", "classify-"):
        yield from read_csv_rows(csv_path, CLASSIFY_COLUMNS)


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
    violations = []

    def violate(kind, detail, drive, path, other_drive="", other_path="",
                dest=""):
        violations.append({
            "kind": kind, "detail": detail, "source_drive": drive,
            "source_path": path, "other_drive": other_drive,
            "other_path": other_path, "dest_path": dest})

    # ---- gather every actionable row, with its measured hash -------------
    # Only the fields the plan needs are kept: at fleet scale the full row
    # dicts would be several GB resident.
    copies, deletes = [], []
    held = defaultdict(int)
    held_bytes = 0
    hashes_by_run = {}
    volumes = {}
    for name, run_dir in runs:
        hashes_by_run[name] = _run_hashes(run_dir)
        volumes[name] = run_volumes(run_dir)
        for row in _iter_classified(run_dir):
            cls = row["class"]
            if cls in _COPY_CLASSES:
                copies.append((name, row["path"], row["size"],
                               _dest_of(row), row["nas_tier"] or "hdd-mirror",
                               bool(row["proposed_path"]), cls,
                               row["confidence"]))
            elif cls in _DELETE_CLASSES:
                deletes.append((name, row["path"], row["size"], cls,
                                row["dupe_of"], row["confidence"]))
            else:
                held[cls or "(blank)"] += 1
                if row["size"]:
                    held_bytes += int(row["size"])

    # ---- pass 1: copies. Every destination is unique or the plan stops ---
    copies.sort(key=lambda t: (t[0], t[1].casefold()))
    plan_rows = []
    seq = 0
    dest_map = {}    # (tier, dest casefold) -> (sha, seq, drive, path)
    copy_seq = defaultdict(dict)  # run name -> norm_key(source) -> seq
    merged = qualified = unhashed_copies = 0
    for name, path, size, dest, tier, has_dest, cls, conf in copies:
        if not has_dest:
            violate("no-destination", f"{cls} row has no proposed_path",
                    name, path)
            continue
        sha = hashes_by_run[name].get(norm_key(path), "")
        key = (tier, dest.casefold())
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
            # Resolve it by qualifying the destination with the run folder
            # this file came from; overwriting is never an option.
            dest = name + "\\" + dest
            key = (tier, dest.casefold())
            if key in dest_map:
                q_sha, _q_seq, q_drive, q_path = dest_map[key]
                violate("destination-collision",
                        "two files still collide after qualifying the "
                        "destination with the drive they came from",
                        name, path, q_drive, q_path, dest)
                continue
            qualified += 1
            note = (f"destination qualified with the source drive: "
                    f"{p_drive} already claims this path")
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
            "source_volume": volumes[name], "note": note,
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

    def hold_delete(reason, size):
        nonlocal held_delete_bytes
        held_deletes[reason] += 1
        held_delete_bytes += size

    for name, path, size_s, cls, dupe_of, conf in deletes:
        sha = hashes_by_run[name].get(norm_key(path), "")
        size = int(size_s) if size_s else 0
        rec = {
            "seq": 0, "action": "delete-candidate", "depends_on": "",
            "source_drive": name, "source_path": path,
            "size": size_s, "sha256": sha, "verify": "sha256",
            "nas_tier": "", "dest_path": "",
            "keeper_path": dupe_of, "keeper_sha256": "",
            "class": cls, "confidence": conf,
            "source_volume": volumes[name], "note": "",
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
                            "SHA256 (close the coverage gap first)", size)
                continue
            if kseq is None:
                hold_delete("the keeper is not scheduled to be copied, so "
                            "this delete cannot be ordered after it", size)
                continue
            rec["depends_on"] = kseq
            rec["keeper_sha256"] = keeper_sha
        elif cls == "EXACT_DUPE_OF_D":
            if not sha:
                hold_delete("no measured SHA256 for a dupe-of-D row", size)
                continue
            # byte-equality with the D: reference came from a full hash; the
            # executor re-verifies the D: file itself before deleting
            rec["depends_on"] = "D-REF"
            rec["keeper_sha256"] = sha
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
                            "file is never deleted on its path alone", size)
                continue
        seq += 1
        rec["seq"] = seq
        plan_rows.append(rec)

    # ---- violations stop everything --------------------------------------
    plan_csv = os.path.join(out_dir, "plan.csv")
    if violations:
        vio_csv = os.path.join(out_dir, "plan-violations.csv")
        with CsvRewriter(vio_csv, VIOLATION_COLUMNS) as w:
            for v in violations:
                w.write(v)
        # a plan.csv from an earlier successful build must not survive a
        # build that found violations - an executor could pick up the stale
        # file. Rewrite it to header-only (atomic) rather than deleting.
        if os.path.exists(plan_csv):
            with CsvRewriter(plan_csv, PLAN_COLUMNS):
                pass
        atomic_write_json(os.path.join(out_dir, "plan-info.json"),
                          {"state": "VIOLATIONS - NO PLAN",
                           "violations": len(violations)})
        # a report from an earlier successful build claims to be "the
        # complete input for execution" - it must not outlive the plan it
        # described
        write_text(os.path.join(out_dir, "plan-report.md"), "\n".join([
            "# Execution plan - NOT BUILT", "",
            f"{len(violations):,} row(s) could not be proven safe, so no "
            f"plan was written. There is nothing here to execute.", "",
            "Every problem row is listed in `plan-violations.csv`.", ""]))
        by_kind = Counter(v["kind"] for v in violations)
        raise SystemExit(
            f"NO PLAN WRITTEN: {len(violations):,} row(s) cannot be proven "
            f"safe - " +
            ", ".join(f"{k} {n:,}" for k, n in by_kind.most_common()) +
            f". Every one is listed with its counterpart in {vio_csv}. "
            f"An unprovable pair usually means a file was never hashed "
            f"(its size was unique on its own drive): closing the coverage "
            f"gap first - Close the Gap.bat - resolves those.")

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

    provenance = {}
    for name, run_dir in runs:
        provenance[name] = load_json(
            os.path.join(run_dir, "run-info.json")) or \
            {"note": "unrecorded (classified before provenance existed)"}

    info = {
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
        f"- {qualified:,} destinations qualified with their source drive "
        f"because another drive already claimed that path (drives are "
        f"scanned one at a time, so classification cannot see the clash)",
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
        f"- {unhashed_copies:,} copy rows have no measured SHA256 (their "
        f"size never collided, so triage never read them). Copying is "
        f"non-destructive: the executor hashes them while reading and "
        f"verifies the destination against that. No DELETE row lacks a "
        f"measured hash - those are held above.",
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
