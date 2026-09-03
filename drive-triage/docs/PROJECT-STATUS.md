# Project status — drive-triage

Handoff brief for a fresh Claude/Cowork session. Written 2026-09-03 against
branch `claude/external-drive-triage-b44sd8`.

**Read `../../CLAUDE.md` before replying to the user.** The response-format
rules there are strict and were established after repeated correction.

---

## 1. Where the operation stands

**Enumeration, gap closing and the cross-drive comparison are complete.**
After `hashgaps` was run against every reachable target, the coverage gap
fell from 140,041 unhashed files to **3,593**, and the cross-drive figure
rose from 74,550 / 1,060.80 GB to **144,709 pieces of content on more than
one drive, 3,977.36 GB reclaimable**. Five inventory rows record something
that could not be read at all; their contents are in no comparison.

All 15 run folders under `C:\DEV\triage\` are
scanned and reported. Each target has its own folder because several
physical drives share a drive letter — eight of the externals were all
mounted as `F:`.

| Run folder | Target | Files |
|---|---|---|
| `WD_PASSPORT_HDD_A` | WD Passport HDD (`F:`) | 834,253 |
| `OLD-HDD_ARCHIVE_1` | old HDD archive (`F:`) | 327,191 |
| `NAS_fastwork` | `\\100.76.11.114\fastwork` | 306,904 |
| `NAS_PHOTOS` | `\\100.76.11.114\photos` | 56,952 |
| `D1-NVME-B` | NVMe in TerraMaster D1 (`F:`) | 37,213 |
| `NAS_DATA` | `\\100.76.11.114\data` | 31,946 |
| `Samsung_T7` | Samsung T7 (`F:`) | 9,029 |
| `D1-NVME` | NVMe in TerraMaster D1 (`F:`) | 8,570 |
| `NAS_VIDEO` | `\\100.76.11.114\video` | 467 |
| `T7-BEIGE-2TB` | Samsung T7, beige (`F:`) | 374 / 753.77 GB |
| `SAMSUNG_T5_1TB_A` | Samsung T5 1TB (`F:`) | 211 |
| `NAS_BACKUPS`, `NAS_PUBLIC` | NAS shares | empty |
| `LAPTOP-HDD-DATA1/2` | Benfei 3.5" HDD, 2 partitions | empty (confirmed by owner) |
| `FASTWORK` | abandoned partial run, no inventory | — |

## 2. What the cross-drive comparison found

Across all 15, after the gap was closed: **144,709 pieces of content on more
than one drive, 3,977.36 GB reclaimable.** The relationships below are from
the earlier, pre-gap-closing pass and understate the totals; the current
per-pair breakdown is in `_cross-drive/reports/cross-drive-duplicates.md`.

| Pair | Shared |
|---|---:|
| NAS_fastwork ↔ WD_PASSPORT_HDD_A | 155.59 GB |
| NAS_DATA ↔ T7-BEIGE-2TB | 107.10 GB |
| NAS_DATA ↔ Samsung_T7 | 16.78 GB |
| NAS_DATA ↔ NAS_VIDEO | 16.78 GB |
| NAS_PHOTOS ↔ OLD-HDD_ARCHIVE_1 | 12.82 GB |

Redundancy is concentrated: `WD_PASSPORT_HDD_A` holds 157.89 GB that exists
elsewhere, `T7-BEIGE-2TB` 107.10 GB. The single biggest pattern is the TIFFANY
video set, which exists in **four** places (two paths on NAS_DATA, two on
T7-BEIGE-2TB) — 13.20 GB, 11.81 GB, 10.03 GB and so on, per file.

Three caveats a reader must carry:

1. **Presence-only.** Matches are byte-certain, but "no match" usually means
   "never hashed", not "unique".
2. **Not additive.** The cross-drive figure counts extra copies on the same
   drive, which each drive's own DUPE_EXTERNAL total already counted.
3. **Different survivors.** Within a run the keeper is elected deliberately
   (taxonomy shape > non-generic parent > depth > mtime); across runs
   redundancy is charged to every drive after the alphabetically first. The
   two reports can disagree about which copy to keep.

## 3. The coverage gap, and what is being done about it

**140,041 files / 2,977.81 GB could not be compared.** Each run built its own
size census, so a file whose size was unique on its own drive was never
hashed — even if a twin sits on another drive.

`hashgaps` (`Close the Gap.bat`) was built for exactly this and has now been
**run against every reachable target**, one drive letter at a time. It hashes
only the listed files and appends into the same per-run CSVs, so the
following `crossdrive` picked them up with no re-scan. 3,593 files remain
unhashed: chiefly ACL-locked Windows key material inside an old C: backup on
`OLD-HDD_ARCHIVE_1`, which no re-run can read.

Operational constraints the owner is working under:

- The gap list holds absolute paths (`F:\...`), so **each external must be
  mounted at the letter it was scanned at.** Seven of them were scanned at
  `F:`, so they go one at a time. (Offered and declined: a `--at G:`
  remapping flag.)
- **Two turns per drive.** A file only earns a whole-file hash once another
  drive's 64KB prefix matches it, so drive A contributes its prefix on turn
  one and comes back for its own hash after drive B has been seen.
- Done when a run's summary shows nothing pending and nothing under NOT DONE.
  Then re-run `Compare All Drives.bat`.

All of those drives have now been through it. Two T7 Shields share an
identical volume label AND an identical byte count, and the content-sample
check told them apart correctly — it accepted `T7-BEIGE-2TB` and refused
`Samsung_T7` on the same attachment.

**Next in the sequence: `reclassify`, then `plan`.** The per-drive classify
outputs still predate the 137,000 newly-hashed files, so the plan would
otherwise be built from the old answer.

## 4. Open direction decisions

D2 (the plan stage) and D3 (close the gap) are **built and shipped**, along
with the two high-severity classification defects. D1 and D4 remain, and
were explicitly deferred by the owner.

### D2 — the plan stage — DONE

`python -m triage plan` (Build the Plan.bat) emits one ordered,
collision-free plan carrying SHA256 on every row. Deletes name their
keeper's copy row and cannot precede it; a delete that cannot be proven is
held and explained rather than emitted; destination clashes across drives
are qualified by source drive; every row carries the volume label+size its
drive was inventoried with, since all six externals mounted as `F:`; and a
contradiction halts the build and invalidates any previous plan. See README,
"The plan stage".

### D1 — Close the decision loop, or leave it advisory

`decision-list.md` asks the user to answer in bulk, but nothing reads answers
back: no overrides file, no config key, no ingest path. Re-running `classify`
regenerates the identical list, and the D-numbers are assigned by descending
byte total at render time, so they are **not stable identifiers**.

- **A (recommended)** — an `overrides.csv` that `classify` reads, keyed on a
  stable group key (reason + path prefix). ~1 day. Answers survive re-runs.
- **B** — tune the hard-coded constants instead. Every answer becomes a Python
  edit in a session.
- **C** — treat the list as advice and sort by hand.

### D4 — Make the cross-drive result actionable, or keep it as a signal

Biggest number in the project, least usable: a CSV with no action column, no
keeper election, no manifest.

- **A (recommended)** — reuse `_keeper_score` across runs, add an action
  column, subtract within-drive duplication so the headline figures stop
  overlapping.
- **B** — use it only to aim manual review. Reasonable given how concentrated
  the redundancy is: the TIFFANY set and the WD Passport → NAS copy are two
  folder-level decisions, not 74,550 file-level ones.

## 5. Defect register

**Fixed since:** classification could only be refreshed one drive at a time,
which both re-derived a different activity cutoff per drive and left the
fleet half-updated after `hashgaps` added hashes — `reclassify` now re-runs
every run folder from the recorded CSVs against one cutoff, reloading the D
reference per folder (`run_classify` drops reference paths under its roots
in place, so a shared object would have shrunk the reference drive by drive).
A run folder whose scan root cannot be recovered from its own inventory is
named and left alone rather than guessed at. Also: `plan.py`'s `_basename`
docstring raised a `SyntaxWarning` on every run, and `__pycache__` was
tracked in git.

**Fixed earlier:** the crossdrive workspace now goes through the full
write guard (canonical path, volume identity, Windows system-drive rule)
instead of a lexical check; the gap list states the real per-file reason and
reads the full-hash CSVs, so a failed whole-file read is no longer reported as
a file whose prefix matched nothing; files proven unique by their 64KB prefix
drop off the gap list, so the number converges; unexamined inventory rows are
reported even when gaps exist; README's stale test count, output layout and
per-drive-independence claims corrected.

**Still open:**

| Sev | Defect | Where |
|---|---|---|
| Live / high | Projects keyed by folder **name** only. Two unrelated "Smith Wedding" folders share one activity timestamp (a 2024 shoot drags a 2016 shoot into fastwork) and are proposed into the **same destination**, where same-named camera files collide. Inactive media escapes only because its path carries the year. | `classify.py` — `project_from_parts`, `collect_project_activity`, `fastwork_subfolder` |
| Live / high | Classification is **time-dependent** and unversioned. The fastwork/hdd-mirror split uses the clock at classify time minus `active_project_days`; re-running months later silently moves projects between tiers and changes NAS sizing. No output records tool version, config, D-reference, or cutoff. | `classify.py` |
| Live / med | `hash.done` fingerprint is `[slug, row_count]`. A refresh deleting one file and adding another leaves the count identical, so a marker written *before* the refresh still validates. | `hashing.py` — `hash_fingerprint` / `check_hash_marker` |
| Live / med | `--refresh` deletes the old inventory **before** the new walk is known to succeed. The one non-atomic transition in the tool, and it sits behind a y/N prompt in the launcher. | `inventory.py` |
| Live / med | Stale prefix rows win in the ordinary full-hash stage: two code paths keep the *last* row per path, `run_full_stage` keeps the *first* that passes its test. One-line fix (iterate `_load_hashed(...).values()`). Note `hashgaps` does not have this bug. | `hashing.py` — `run_full_stage` |
| Latent / med | Two targets with the same basename collide in the main pipeline: `\\NAS1\photos` and `\\NAS2\photos` both slug to `photos`, and in one invocation the second is **not scanned at all** while the pipeline reports success. The launcher passes one target per run, which is why this has not bitten. (`hashgaps` handles multi-slug run folders correctly.) | `util.py` — `drive_slug` |
| Low | Unexamined-directory rows are never retracted, so the decision list keeps reporting a directory a later resume fully inventoried. Only `--refresh` clears it. Placeholder rows carry no size, so there is no "unknown bytes" figure anywhere. | `inventory.py` |
| Low | Launcher: an empty name answer puts a trailing backslash inside the quoted `--output-dir`. `if errorlevel 1` after `probe` reports Python-missing, a bad config key and a guard refusal all as "CANNOT REACH THE TARGET". | `Triage a Drive.bat` |
| Low | The read-only proof test compares two sets of relative paths — it would pass if a file's contents were rewritten. A per-file size+SHA256 comparison is a small upgrade. The only permission-denied test skips as root, which is how CI runs. | `tests/test_triage.py` |

## 6. What is guaranteed

- No delete/move/rename against any scanned path. `shutil` never imported;
  `os.remove` only regenerates the tool's own outputs. Test-enforced.
- No network access, structurally — no network-capable imports, only fixed
  read-only PowerShell volume queries. Stdlib only. Test-enforced.
- C: and D: hard-refused as scan roots in two independent places.
- Output directories **and the crossdrive workspace** are guarded before
  anything is created.
- Reparse points never traversed, never opened.
- A read error can only cause a *missed* duplicate, never a false
  delete-candidate: dupes require full SHA256 equality.
- `hashgaps` will not touch a drive it cannot prove is the one that was
  scanned: the recorded volume label+size must still match, a spread sample of
  already-hashed files is re-read and must match by content, absent samples
  are disqualifying, the check repeats before the whole-file pass, and every
  file is re-stat'd so a changed one is left for the next run.
- Nothing has been executed against user data.

Still open from the original mission: `C:\DEV\script-security-policy.md` has
never been reachable from the cloud container. `docs/SECURITY-PROFILE.md`
documents every read and write and should be checked against that policy
before the execution phase.

## 7. Codebase facts

- `drive-triage/triage/` — ~4,000 lines, Python 3.9+, stdlib only, zero deps.
- `drive-triage/tests/test_triage.py` — 117 tests, all pass, 1 skipped as root.
- Eleven subcommands: `enumerate`, `probe`, `inventory`, `hash`, `classify`,
  `reclassify`, `report`, `crossdrive`, `hashgaps`, `plan`, `all`. Flags are
  global.
- User-facing entry points are five `.bat` launchers — `Triage a Drive.bat`,
  `Compare All Drives.bat`, `Close the Gap.bat`, `Re-Classify All
  Drives.bat`, `Build the Plan.bat`. The user runs the tool by
  double-clicking; assume no CLI familiarity.
- Fleet order after the per-drive scans: `crossdrive` → `hashgaps` (repeat
  until nothing is pending) → `crossdrive` → `reclassify` → `plan`.
