"""Cross-drive duplicate analysis over completed per-drive runs.

Each drive was triaged into its own workspace folder, so its duplicate
detection only ever saw that one drive. This module compares the SHA256
values already recorded by those runs, across all of them at once.

Content hashes are compared, never paths - which is what makes this work
despite several different physical drives having all been mounted as F:.
Each run folder's NAME identifies the drive.

Nothing here touches a scanned drive: it reads only the CSVs the runs
already wrote.

Coverage limit, reported honestly in the output: a file was hashed by its
run only if its size occurred more than once on ITS OWN drive (or matched
the D: reference). A file that was size-unique on its own drive but has a
twin on another drive was never hashed, so it cannot be compared here.
`cross-drive-gaps.csv` lists exactly those files so a targeted hashing pass
can close the gap without re-reading everything.
"""

import os
from collections import Counter, defaultdict

from .util import (
    HASH_COLUMNS, INVENTORY_COLUMNS, CsvRewriter, fmt_gb, read_csv_rows,
    write_text,
)

GROUP_COLUMNS = ["sha256", "size", "copies", "drives", "paths"]
GAP_COLUMNS = ["drive", "path", "size", "reason"]
CROSS_DIR = "_cross-drive"


def find_runs(workspace):
    """Yield (drive_name, run_dir) for every completed run folder."""
    for name in sorted(os.listdir(workspace)):
        run_dir = os.path.join(workspace, name)
        if name == CROSS_DIR or not os.path.isdir(run_dir):
            continue
        if os.path.isdir(os.path.join(run_dir, "inventory")):
            yield name, run_dir


def _csvs(run_dir, sub, prefix):
    d = os.path.join(run_dir, sub)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.startswith(prefix) and f.endswith(".csv")]


def iter_hashes(run_dir):
    """Yield (path, size:int, full_sha256) for rows with a full hash."""
    for csv_path in (_csvs(run_dir, "hashes", "prefix-") +
                     _csvs(run_dir, "hashes", "full-")):
        for row in read_csv_rows(csv_path, HASH_COLUMNS):
            if row["error"] or not row["full_sha256"] or not row["size"]:
                continue
            yield row["path"], int(row["size"]), row["full_sha256"]


def iter_inventory_rows(run_dir):
    for csv_path in _csvs(run_dir, "inventory", "inventory-"):
        for row in read_csv_rows(csv_path, INVENTORY_COLUMNS):
            if row["error"] or not row["size"]:
                continue
            size = int(row["size"])
            if size > 0:
                yield row["path"], size


def analyze(workspace, logger):
    runs = list(find_runs(workspace))
    if len(runs) < 2:
        raise SystemExit(
            f"need at least two completed run folders under {workspace} to "
            f"compare; found {len(runs)}.")
    logger.info("comparing %d runs: %s", len(runs),
                ", ".join(n for n, _ in runs))

    # ---- pass 1: which content hashes appear on more than one drive -------
    drives_by_sha = defaultdict(set)
    hashed_paths = defaultdict(set)   # drive -> set of hashed paths
    for name, run_dir in runs:
        n = 0
        for path, size, sha in iter_hashes(run_dir):
            drives_by_sha[sha].add(name)
            hashed_paths[name].add(path)
            n += 1
        logger.info("%s: %d files with a full hash", name, n)
    shared = {sha for sha, ds in drives_by_sha.items() if len(ds) > 1}
    del drives_by_sha
    logger.info("%d content hashes appear on more than one drive", len(shared))

    # ---- pass 2: collect the actual copies of those hashes ---------------
    groups = defaultdict(list)        # sha -> [(drive, path, size)]
    for name, run_dir in runs:
        for path, size, sha in iter_hashes(run_dir):
            if sha in shared:
                groups[sha].append((name, path, size))

    out_dir = os.path.join(workspace, CROSS_DIR)
    group_csv = os.path.join(out_dir, "manifests",
                             "cross-drive-duplicates.csv")
    pair_bytes = Counter()            # (driveA, driveB) -> bytes shared
    drive_redundant = Counter()       # drive -> bytes it holds redundantly
    total_groups = 0
    reclaimable = 0
    biggest = []
    with CsvRewriter(group_csv, GROUP_COLUMNS) as w:
        for sha, copies in groups.items():
            # one row per distinct (drive, path); a drive may hold several
            uniq = sorted(set(copies))
            drives = sorted({d for d, _, _ in uniq})
            if len(drives) < 2:
                continue
            size = uniq[0][2]
            total_groups += 1
            # keeping one copy overall reclaims every other copy
            reclaimable += size * (len(uniq) - 1)
            for i, a in enumerate(drives):
                for b in drives[i + 1:]:
                    pair_bytes[(a, b)] += size
            for d in drives[1:]:
                drive_redundant[d] += size
            w.write({
                "sha256": sha,
                "size": size,
                "copies": len(uniq),
                "drives": " | ".join(drives),
                "paths": " | ".join(f"[{d}] {p}" for d, p, _ in uniq),
            })
            item = (size, sha, uniq)
            if len(biggest) < 25:
                biggest.append(item)
                biggest.sort(reverse=True)
            elif item > biggest[-1]:
                biggest[-1] = item
                biggest.sort(reverse=True)

    # ---- gap analysis: what could not be compared -------------------------
    census = Counter()
    per_drive_sizes = {}
    for name, run_dir in runs:
        sizes = Counter()
        for _, size in iter_inventory_rows(run_dir):
            sizes[size] += 1
        per_drive_sizes[name] = sizes
        census.update(sizes)

    gap_csv = os.path.join(out_dir, "manifests", "cross-drive-gaps.csv")
    gap_n, gap_bytes = 0, 0
    gap_by_drive = Counter()
    with CsvRewriter(gap_csv, GAP_COLUMNS) as w:
        for name, run_dir in runs:
            own = per_drive_sizes[name]
            for path, size in iter_inventory_rows(run_dir):
                if path in hashed_paths[name]:
                    continue
                # size unique on its own drive (so never hashed) but present
                # on at least one other drive: a possible cross-drive dupe
                if census[size] > own[size]:
                    gap_n += 1
                    gap_bytes += size
                    gap_by_drive[name] += 1
                    w.write({
                        "drive": name, "path": path, "size": size,
                        "reason": "size matches a file on another drive but "
                                  "was never hashed (was size-unique on its "
                                  "own drive)",
                    })
    if gap_n == 0:
        os.remove(gap_csv)

    # ---- report ----------------------------------------------------------
    lines = [
        "# Cross-drive duplicate analysis",
        "",
        f"Compared {len(runs)} drives: " + ", ".join(n for n, _ in runs),
        "",
        "Matches are byte-certain (full SHA256 equality). Nothing has been "
        "deleted or moved - this is a report.",
        "",
        "## Headline",
        "",
        f"- **{total_groups:,} piece{'' if total_groups == 1 else 's'} of "
        f"content exist{'s' if total_groups == 1 else ''} on more than one "
        f"drive**",
        f"- **{fmt_gb(reclaimable)} reclaimable** by keeping a single copy "
        f"of each",
        "",
    ]
    if pair_bytes:
        lines += ["## Shared content between drive pairs", "",
                  "| Drive A | Drive B | Shared |", "|---|---|---:|"]
        for (a, b), n in pair_bytes.most_common(30):
            lines.append(f"| {a} | {b} | {fmt_gb(n)} |")
        lines.append("")
    if drive_redundant:
        lines += ["## Redundant content per drive",
                  "",
                  "How much of each drive already exists on another drive "
                  "listed above it.",
                  "",
                  "| Drive | Redundant |", "|---|---:|"]
        for d, n in drive_redundant.most_common():
            lines.append(f"| {d} | {fmt_gb(n)} |")
        lines.append("")
    if biggest:
        lines += ["## 25 largest duplicated files", ""]
        for size, _sha, uniq in biggest:
            lines.append(f"- {fmt_gb(size)} x{len(uniq)} copies")
            for d, p, _ in uniq:
                lines.append(f"    - [{d}] {p}")
        lines.append("")
    lines += [
        "## Coverage - what this could NOT compare",
        "",
    ]
    if gap_n:
        lines += [
            f"**{gap_n:,} files ({fmt_gb(gap_bytes)}) could not be "
            f"compared.** Each run only hashed files whose size repeated on "
            f"its own drive, so a file that was size-unique on its drive was "
            f"never hashed - even if an identical copy sits on another "
            f"drive.",
            "",
            "| Drive | Unhashed files that may have twins elsewhere |",
            "|---|---:|",
        ]
        for d, n in gap_by_drive.most_common():
            lines.append(f"| {d} | {n:,} |")
        lines += [
            "",
            "`manifests/cross-drive-gaps.csv` lists them. Closing this gap "
            "needs a hashing pass over those files only - far less work "
            "than re-scanning the drives.",
            "",
        ]
    else:
        lines += ["Every file that could have a twin on another drive was "
                  "hashed; this comparison is complete.", ""]
    lines += [
        "## Files",
        "",
        "- `manifests/cross-drive-duplicates.csv` - every duplicated piece "
        "of content, with each copy's drive and path",
    ]
    if gap_n:
        lines.append("- `manifests/cross-drive-gaps.csv` - files that still "
                     "need hashing to be comparable")
    report = os.path.join(out_dir, "reports", "cross-drive-duplicates.md")
    write_text(report, "\n".join(lines) + "\n")
    return {"runs": [n for n, _ in runs], "groups": total_groups,
            "reclaimable": reclaimable, "gap_files": gap_n,
            "report": report, "groups_csv": group_csv}
