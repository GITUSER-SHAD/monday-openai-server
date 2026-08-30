"""Phase 3: reports, master plan, move/copy manifests, decision list.

Pure computation over classify CSVs, all streaming - memory stays flat no
matter how many millions of rows a drive has. Nothing here reads target
drives and nothing is ever executed against them - manifests are proposals
for a later, separately-approved session.
"""

import heapq
import os
import re
from collections import Counter, defaultdict

from .util import (
    CLASSIFY_COLUMNS, MANIFEST_COLUMNS, CsvRewriter, drive_slug, fmt_gb,
    read_csv_rows, write_text,
)
from .classify import classify_paths

ACTION_BY_CLASS = {
    "MEDIA": "copy",
    "RECORDS": "copy",
    "ARCHIVE_BOX": "copy",
    "UNKNOWN": "hold",
    "JUNK": "delete-candidate",
    "EXACT_DUPE_OF_D": "delete-candidate",
    "DUPE_EXTERNAL": "delete-candidate",
}


def iter_classified(cfg, root):
    path = classify_paths(cfg, root)
    if not os.path.exists(path):
        raise SystemExit(
            f"no classification for {root} ({path} missing) - run "
            f"`python -m triage classify` first.")
    yield from read_csv_rows(path, CLASSIFY_COLUMNS)


def _size(row):
    return int(row["size"]) if row["size"] else 0


def _top_component(root, path):
    return re.split(r"[\\/]", os.path.relpath(path, root))[0]


# ---------------------------------------------------------------------------
# Deliverable 1: per-drive triage report
# ---------------------------------------------------------------------------

def per_drive_report(cfg, root):
    slug = drive_slug(root)
    by_class = defaultdict(lambda: [0, 0])  # class -> [count, bytes]
    top_dirs_dupe = Counter()
    boxes = defaultdict(lambda: [0, 0])
    errors = 0
    biggest = []  # heap of (size, path, class)
    for i, r in enumerate(iter_classified(cfg, root)):
        c, sz = r["class"], _size(r)
        by_class[c][0] += 1
        by_class[c][1] += sz
        if c in ("EXACT_DUPE_OF_D", "DUPE_EXTERNAL"):
            top_dirs_dupe[_top_component(root, r["path"])] += sz
        if c == "ARCHIVE_BOX":
            boxes[r["subclass"]][0] += 1
            boxes[r["subclass"]][1] += sz
        if r["subclass"] == "stat-error":
            errors += 1
        item = (sz, i, r["path"], c)
        if len(biggest) < 20:
            heapq.heappush(biggest, item)
        elif item > biggest[0]:
            heapq.heapreplace(biggest, item)

    total_files = sum(v[0] for v in by_class.values())
    total_bytes = sum(v[1] for v in by_class.values())

    lines = [
        f"# Triage report - drive {slug} ({root})",
        "",
        f"Files: {total_files:,}   Data: {fmt_gb(total_bytes)}",
        "",
        "## By class",
        "",
        "| Class | Files | Size |",
        "|---|---:|---:|",
    ]
    for c in sorted(by_class, key=lambda c: -by_class[c][1]):
        n, b = by_class[c]
        lines.append(f"| {c} | {n:,} | {fmt_gb(b)} |")
    reclaim = (by_class["EXACT_DUPE_OF_D"][1] + by_class["DUPE_EXTERNAL"][1] +
               by_class["JUNK"][1])
    lines += ["", f"**Reclaimable (dupes + junk, pending approval): "
                  f"{fmt_gb(reclaim)}**", ""]
    if boxes:
        lines += ["## Archive boxes (kept intact)", ""]
        for name, (n, b) in sorted(boxes.items(), key=lambda kv: -kv[1][1]):
            lines.append(f"- **{name}**: {n:,} files, {fmt_gb(b)}")
        lines.append("")
    if top_dirs_dupe:
        lines += ["## Top dupe-heavy top-level folders", ""]
        for d, b in top_dirs_dupe.most_common(10):
            lines.append(f"- {d}: {fmt_gb(b)} duplicated")
        lines.append("")
    lines += ["## 20 largest files", ""]
    for sz, _, path, c in sorted(biggest, reverse=True):
        lines.append(f"- {fmt_gb(sz):>10}  [{c}] {path}")
    if errors:
        lines += ["", f"Unreadable/stat-error files: {errors} "
                      f"(see logs and classify CSV)"]
    out = os.path.join(cfg["output_dir"], "reports", f"report-{slug}.md")
    write_text(out, "\n".join(lines) + "\n")
    return out


# ---------------------------------------------------------------------------
# Deliverable 2: master consolidated plan
# ---------------------------------------------------------------------------

def master_plan(cfg, roots):
    by_class = defaultdict(lambda: [0, 0])
    tier = defaultdict(lambda: [0, 0])
    tree = defaultdict(lambda: [0, 0])   # first two proposed-path levels
    for root in roots:
        for r in iter_classified(cfg, root):
            sz = _size(r)
            by_class[r["class"]][0] += 1
            by_class[r["class"]][1] += sz
            if r["nas_tier"] and r["nas_tier"] != "none":
                tier[r["nas_tier"]][0] += 1
                tier[r["nas_tier"]][1] += sz
            if r["proposed_path"]:
                parts = r["proposed_path"].split("\\")
                key = "\\".join(parts[:2])
                tree[key][0] += 1
                tree[key][1] += sz

    lines = ["# Master consolidated triage plan", "",
             f"Drives: {', '.join(drive_slug(r) for r in roots)}",
             "", "## Totals by class", "",
             "| Class | Files | Size |", "|---|---:|---:|"]
    for c in sorted(by_class, key=lambda c: -by_class[c][1]):
        n, b = by_class[c]
        lines.append(f"| {c} | {n:,} | {fmt_gb(b)} |")
    reclaim = (by_class["EXACT_DUPE_OF_D"][1] +
               by_class["DUPE_EXTERNAL"][1] + by_class["JUNK"][1])
    unique = (by_class["MEDIA"][1] + by_class["RECORDS"][1] +
              by_class["ARCHIVE_BOX"][1])
    lines += ["",
              f"**Total reclaimable (exact dupes vs D:, external dupes, "
              f"junk): {fmt_gb(reclaim)}**",
              f"**Total unique content to migrate: {fmt_gb(unique)}**",
              "", "## By NAS destination tier", "",
              "| Tier | Files | Size |", "|---|---:|---:|"]
    for t in sorted(tier, key=lambda t: -tier[t][1]):
        n, b = tier[t]
        lines.append(f"| {t} | {n:,} | {fmt_gb(b)} |")
    lines += ["", "## Proposed final tree (top 2 levels)", ""]
    for key in sorted(tree):
        n, b = tree[key]
        lines.append(f"- `{key}`  ({n:,} files, {fmt_gb(b)})")
    out = os.path.join(cfg["output_dir"], "reports", "master-plan.md")
    write_text(out, "\n".join(lines) + "\n")
    return out


# ---------------------------------------------------------------------------
# Deliverable 3: move/copy manifests (nothing executed this session)
# ---------------------------------------------------------------------------

def write_manifests(cfg, roots):
    outs = []
    for root in roots:
        slug = drive_slug(root)
        out = os.path.join(cfg["output_dir"], "manifests",
                           f"manifest-{slug}.csv")
        with CsvRewriter(out, MANIFEST_COLUMNS) as w:
            for r in iter_classified(cfg, root):
                w.write({
                    "action": ACTION_BY_CLASS.get(r["class"], "hold"),
                    "source_path": r["path"],
                    "proposed_path": r["proposed_path"],
                    "proposed_name": r["proposed_name"],
                    "nas_tier": r["nas_tier"],
                    "class": r["class"],
                    "subclass": r["subclass"],
                    "size": r["size"],
                    "confidence": r["confidence"],
                    "evidence": r["evidence"],
                })
        outs.append(out)
    return outs


# ---------------------------------------------------------------------------
# Deliverable 4: decision list - one line per ambiguity group
# ---------------------------------------------------------------------------

def _reason_key(row):
    ev = row["evidence"].split(";")[0]
    ev = re.sub(r"\d+", "N", ev)[:70]
    return f"{row['class']}/{row['subclass']}: {ev}"


def decision_list(cfg, roots):
    groups = {}
    for root in roots:
        for r in iter_classified(cfg, root):
            needs = (r["class"] == "UNKNOWN" or r["confidence"] == "low" or
                     "PROBABLE dupe of D:" in r["evidence"] or
                     "sole survivor" in r["evidence"])
            if not needs:
                continue
            key = (drive_slug(root), _reason_key(r),
                   _top_component(root, r["path"]))
            g = groups.setdefault(key, {"count": 0, "bytes": 0, "ex": []})
            g["count"] += 1
            g["bytes"] += _size(r)
            if len(g["ex"]) < 3:
                g["ex"].append(r["path"])

    lines = ["# Decision list - answer in bulk", "",
             "Each line is one judgment call covering the whole group. "
             "Reply like: `D3: media, year 2019` or `D7: junk, delete`.",
             ""]
    for i, (key, g) in enumerate(sorted(
            groups.items(), key=lambda kv: -kv[1]["bytes"]), start=1):
        drive, reason, top = key
        example = g["ex"][0] if g["ex"] else ""
        lines.append(
            f"- **D{i}** [{drive}:{top}] {reason} - {g['count']:,} files, "
            f"{fmt_gb(g['bytes'])} (e.g. `{example}`)")
    if len(lines) == 4:
        lines.append("(no ambiguities - nothing needs a decision)")
    out = os.path.join(cfg["output_dir"], "reports", "decision-list.md")
    write_text(out, "\n".join(lines) + "\n")
    return out


def run_reports(cfg, roots, logger):
    outs = []
    for root in roots:
        outs.append(per_drive_report(cfg, root))
    outs.append(master_plan(cfg, roots))
    outs.extend(write_manifests(cfg, roots))
    outs.append(decision_list(cfg, roots))
    for o in outs:
        logger.info("wrote %s", o)
    return outs
