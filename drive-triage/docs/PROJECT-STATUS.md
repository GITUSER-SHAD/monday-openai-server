# Project status — drive-triage

Handoff brief for a fresh Claude/Cowork session. Written 2026-09-01 against
commit `fd99ca0` on `claude/external-drive-triage-b44sd8`.

Companion artifact (same content, presented for reading):
https://claude.ai/code/artifact/5c587ba5-518e-40a5-a70d-32a65c95b344

**Read `../../CLAUDE.md` before replying to the user.** Response format rules
there are strict and were established after repeated correction.

---

## 1. Where the operation stands

Eight targets, each triaged into its own folder under `C:\DEV\triage\<NAME>\`
because five different physical drives were all mounted as `F:` at various
points. Folder name — not drive letter — is the identity used downstream.

| Run folder | Device | Status | Files | Data |
|---|---|---|---|---|
| `T7-SHIELD` | Samsung T7 Shield | complete | — | — |
| `WD_PASSPORT` | WD Passport HDD | complete | — | — |
| `LAPTOP-HDD-DATA1` | Benfei HDD, partition 1 | complete | — | — |
| `LAPTOP-HDD-DATA2` | Benfei HDD, partition 2 (`L:`) | complete | — | — |
| `D1-NVME` | TerraMaster D1 NVMe enclosure | complete | — | — |
| `NAS_PHOTOS` | `\\100.76.11.114\photos` | complete | 56,952 | — |
| `T7-BEIGE-2TB` | Samsung T7, beige housing | complete | 374 | 753.77 GB |
| `NAS_fastwork` | `\\100.76.11.114\fastwork` | **stale** | 306,904 | — |

`NAS_fastwork`'s last full pipeline predates both the recycle-bin empty
(14,420 files) and the O(N²) duplicate-group fix. Re-run is queued.

Two runs verified in detail this session:

- **T7-BEIGE-2TB** — 374 files / 753.77 GB. MEDIA 326 (646.65 GB),
  DUPE_EXTERNAL 37 (107.10 GB), UNKNOWN 11 (0.02 GB). All duplication sits
  under one folder, `TIFFANY`. The low file count is correct — large video only.
- **NAS_PHOTOS** — 56,952 rows; 37,862 prefix-hashed, 13,303 full-hashed.
  MEDIA 42,366 · DUPE_EXTERNAL 8,921 · RECORDS 5,156 · UNKNOWN 501 · JUNK 8.
  One directory unexamined (`#recycle`, WinError 59) — recorded, not silent.

## 2. What the numbers say

Across the **six** drives compared so far: 62,661 duplicated pieces,
**571.27 GB** reclaimable. One relationship dominates —
`NAS_fastwork ↔ WD_PASSPORT = 157.83 GB`; the Passport appears to have been
copied wholesale onto the NAS.

Coverage gap: **85,441 files / 1,396.64 GB never compared.**

Three things about these figures a reader must know:

1. **Presence-only.** A file was hashed only if its size repeated *on its own
   drive*, since each drive built its own census. "No match" usually means
   "never hashed", not "unique".
2. **Not additive.** Cross-drive `reclaimable` counts extra copies on the same
   drive, which each drive's own DUPE_EXTERNAL total already counted.
3. **Different survivors.** Within a run the keeper is elected deliberately
   (taxonomy shape > non-generic parent > depth > mtime); across runs
   redundancy is charged to every drive after the alphabetically first. The two
   reports can disagree about which copy to keep.

Also: the cross-drive pass predates `NAS_PHOTOS` and `T7-BEIGE-2TB`, so
571.27 GB is a floor.

## 3. The four decisions

Ranked by downstream work unblocked. **Settle D2 before D1** — the manifest
shape determines what an answer to a decision-list question has to produce.

### D1 — Close the decision loop, or leave it advisory

`decision-list.md` asks the user to answer in bulk, but nothing reads answers
back: no overrides file, no config key, no ingest path. Re-running `classify`
regenerates the identical list. The D-numbers are assigned by descending byte
total at render time, so they are **not stable identifiers** to answer against.

- **A (recommended)** — build an answers file `classify` reads. Cost: a stable
  group key (reason + path prefix), an `overrides.csv` reader, precedence rules.
  ~1 day. Buys: answers survive re-runs.
- **B** — tune the hard-coded constants instead. Cost: every answer becomes a
  Python edit in a session. Loses: user can't answer anything alone.
- **C** — treat the list as advice, sort by hand. Cost: hundreds of manual
  filings per drive. Loses: the automation's main promise.

### D2 — Make the manifests safe to execute, or re-derive safety in the executor

Manifests are proposals and nothing runs them — by design. But as shaped they
cannot drive a safe copy-and-delete phase:

- no SHA256 column, so copy-and-verify can't check against what triage measured;
- no destination-collision detection — two RECORDS files can be renamed into the
  same folder under the same proposed name;
- delete-candidate rows name a keeper but nothing verifies the keeper is
  scheduled to be copied *first*.

- **A (recommended)** — add a `plan` stage emitting a verified, ordered,
  collision-free plan carrying hashes. Buys: the execution session becomes a
  dumb, auditable replay.
- **B** — let the executor derive safety itself. Loses: the planning/execution
  separation the read-only design exists to preserve.

### D3 — Close the 1,397 GB gap, or accept it

The tool names the fix ("a hashing pass over those files only") but no such
command exists and no flag accepts a path list. The gap CSV is also not
accurate enough to drive one blindly: every row carries the same hard-coded
reason while the real test is "no full hash AND size occurs on another drive",
which also catches prefix-hashed singletons, failed reads, and capped runs.

- **A (recommended)** — build `hashgaps`: targeted re-hash from a path list,
  plus fix the gap CSV's reason field. Reads ~85k files, not the fleet.
- **B** — one census across the whole workspace. Loses: one-drive-at-a-time
  scanning, which is how this fleet is actually handled.
- **C** — accept. 571 GB is real and actionable today; the rest stays invisible.

### D4 — Make the cross-drive result actionable, or keep it as a signal

Biggest number in the project, least usable: a CSV with no action column, no
keeper election, no manifest.

- **A (recommended)** — reuse `_keeper_score` across runs, add an action column,
  subtract within-drive duplication so the headline figures stop overlapping.
- **B** — use it only to aim manual review. Reasonable if the Passport really
  was copied wholesale: that's one folder-level decision, not 62,661 file-level
  ones.

## 4. Defect register

Found by adversarial read of the current code. "Live" affects the workflow as
actually used; "latent" is avoided by the launcher's one-drive-per-run pattern.

| Sev | Defect | Where |
|---|---|---|
| Live / high | Projects keyed by folder **name** only. Two unrelated "Smith Wedding" folders share one activity timestamp (a 2024 shoot drags a 2016 shoot into fastwork) and are proposed into the **same destination**, where same-named camera files collide. Inactive media escapes only because its path carries the year. | `classify.py` — `project_from_parts`, `collect_project_activity`, `fastwork_subfolder` |
| Live / high | Classification is **time-dependent** and unversioned. The fastwork/hdd-mirror split uses the clock at classify time minus `active_project_days`; re-running months later silently moves projects between tiers and changes the NAS sizing in `master-plan.md`. No output records tool version, config, D-reference, or cutoff. | `classify.py`; no provenance in any CSV/marker/report |
| Live / med | `hash.done` fingerprint is `[slug, row_count]`. A refresh deleting one file and adding another leaves the count identical, so a marker written *before* the refresh still validates. Sits on the `--refresh` path the launcher offers. | `hashing.py` — `hash_fingerprint` / `check_hash_marker` |
| Live / med | `--refresh` deletes the old inventory **before** the new walk is known to succeed. If the walk is capped, aborts on the 25-unreadable-dirs rule, or the share drops, no complete inventory exists. The one non-atomic transition in the tool. | `inventory.py` refresh block |
| Live / med | Stale prefix rows win in the full-hash stage: two paths keep the *last* row per path, `run_full_stage` keeps the *first* that passes its test. After a file changes, the superseded row is first. One-line fix (iterate `_load_hashed(...).values()`). | `hashing.py` — `run_full_stage` |
| Latent / med | `crossdrive` bypasses every write guard: scan roots forced empty, workspace never guarded — not against scan roots, not against C:/D:, not by the system-drive rule. Default workspace is the **parent** of `output_dir`. Safe today only because the launcher passes `C:\DEV\triage` explicitly. `SECURITY-PROFILE.md`'s "writes go only to output_dir" is inaccurate here. | `cli.py` — `cmd_crossdrive` |
| Latent / med | Two targets with the same basename collide: `\\NAS1\photos` and `\\NAS2\photos` both slug to `photos`. In one run, the second is **not scanned at all** and the pipeline reports success. Volume-identity check is keyed by drive letter only, so UNC and folder targets have no protection. | `util.py` — `drive_slug` |
| Low | Unexamined-directory rows are never retracted, so the decision list keeps reporting a directory that a later resume fully inventoried. Only `--refresh` clears it. The placeholder row has no size, so hidden subtrees contribute zero bytes — there is no "unknown bytes" figure anywhere. | `inventory.py` — `_record_unexamined` |
| Low | Launcher: an empty name answer puts a trailing backslash inside the quoted `--output-dir`, mangling the argument. `if errorlevel 1` after `probe` reports Python-missing, bad config key, and guard refusal all as "CANNOT REACH THE TARGET". | `Triage a Drive.bat` |
| Low | Docs drifted: README says 48 tests (there are 65); documents the flat output layout when the launcher makes one tree per target; claims per-drive independence, which is false after inventory (a detached drive aborts the whole run at hashing). `util.py` cites `tests/test_security.py`, which does not exist. | `README.md`, `util.py` |
| Low | The read-only proof test compares two sets of relative paths — it would pass if a file's contents were rewritten. A per-file size+SHA256 comparison is a small upgrade. The only permission-denied test skips as root, which is how CI runs. | `tests/test_triage.py` |

## 5. What is guaranteed

- No delete/move/rename against any scanned path. `shutil` never imported;
  `os.remove` only regenerates the tool's own outputs. Test-enforced.
- No network access, structurally — no network-capable imports, only fixed
  read-only PowerShell volume queries. Stdlib only. Test-enforced.
- C: and D: hard-refused as scan roots in two independent places.
- Output dirs guarded before anything is created: canonical realpath prefix
  (defeats `\\?\`, UNC, `subst`, junction aliases), `st_dev` volume identity,
  Windows system-drive rule. **Exception: the crossdrive workspace** — see above.
- Reparse points never traversed, never opened.
- A read error can only cause a *missed* duplicate, never a false
  delete-candidate: dupes require full SHA256 equality.
- Nothing has been executed against user data.

Still open from the original mission: `C:\DEV\script-security-policy.md` has
never been reachable from the cloud container. `docs/SECURITY-PROFILE.md`
documents every read and write and is meant to be checked against that policy
before the execution phase — with the crossdrive-workspace item above noted as
a known inaccuracy in it.

## 6. Immediate queue

1. Re-run `NAS_fastwork` with the deletion refresh (launcher → target
   `\\100.76.11.114\fastwork` → name `NAS_fastwork` → deleted files `y`).
2. Re-run `Compare All Drives.bat` — eight targets instead of six. Expect the
   571.27 GB figure to move.
3. Confirm no further physical drives remain unscanned.

## 7. Codebase facts

- `drive-triage/triage/` — 3,482 lines, Python 3.9+, stdlib only, zero deps.
- `drive-triage/tests/test_triage.py` — 65 tests, all pass, 1 skipped as root.
- Eight subcommands: `enumerate`, `probe`, `inventory`, `hash`, `classify`,
  `report`, `crossdrive`, `all`. Flags are global, not per-subcommand.
- User-facing entry points are the two `.bat` launchers, not the CLI. The user
  runs the tool by double-clicking; assume no CLI familiarity.
