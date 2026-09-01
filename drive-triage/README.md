# drive-triage — read-only external drive triage system

Inventories, deduplicates, and classifies everything on your external drives
against the approved taxonomy, and produces reports + move/copy manifests for
later approval. **It never deletes, moves, renames, or modifies your data** —
scanned drives are opened read-only, and the tool refuses to run if its own
output directories sit on a scanned drive.

Built to run on Windows with stock **Python 3.9+** (standard library only —
nothing to `pip install`, no supply chain). Install Python via
`winget install Python.Python.3.12` if needed.

> **Standing rule note:** `C:\DEV\script-security-policy.md` was not
> reachable from the remote session that built this system. Read
> `docs/SECURITY-PROFILE.md` side-by-side with your policy before first run;
> the profile documents every read/write this tool performs.

## Quick start (the whole flow)

```bat
cd C:\DEV\drive-triage          rem or wherever you cloned this
copy config\triage-config.example.json triage-config.json
rem edit triage-config.json: set d_reference_csv to your freshest D: inventory

python -m triage enumerate --config triage-config.json
rem PHASE 0 CHECK-IN: prints all volumes (letter, label, size, bus type).
rem Review C:\DEV\triage\scope.json, set "in_scope" true/false per volume.
rem C:, D: and network mounts are excluded by default and stay excluded.

python -m triage all --config triage-config.json
```

`all` runs inventory → hash → classify → report. Everything verbose goes to
log files under `C:\DEV\logs\drive-triage\`; the console only prints warnings
and per-stage one-liners.

### Stage-by-stage (equivalent, resumable at any point)

```bat
python -m triage inventory --config triage-config.json
python -m triage hash      --config triage-config.json
python -m triage classify  --config triage-config.json
python -m triage report    --config triage-config.json
```

Prioritize the largest drive by running it alone first:

```bat
python -m triage inventory --config triage-config.json --drive E:\
```

## Resumability

- **Interrupt anything** (Ctrl+C, power loss, drive unplugged) and re-run the
  same command: inventory and hashing resume from their CSVs, skipping
  completed work; a torn final CSV line from a crash is tolerated.
- Classification and reports are pure, fast recomputation over the Phase 1
  CSVs — re-running them touches no drive data.
- Per-drive state is independent **at inventory**: a missing drive is
  skipped with a warning. Later stages are not — `hash` and `classify`
  require every in-scope inventory to be complete, so one detached drive
  stops the whole run. Scan one target at a time (which is what
  `Triage a Drive.bat` does) and this never bites.

## Duplicate detection

Two-stage, same approach as the D: reorg: files are hashing candidates only
if their size occurs more than once across all externals + the D: reference;
candidates get a SHA256 of their first 64 KB; full SHA256 runs only where the
prefix group (or a D: size match) can actually decide something. Exact dupes
are **byte-certain** (full SHA256 equality).

The D: reference CSV is auto-parsed (delimiter + column names sniffed). If it
carries SHA256 hashes, dupes-vs-D are exact. If it doesn't, matches are
reported as *probable* (size+name), routed to the decision list, and
`d-hash-request.csv` lists the D: paths whose hashes would settle them.

## Classification

Every file lands in exactly one class, always with stated evidence:

| Class | Meaning | Manifest action |
|---|---|---|
| `EXACT_DUPE_OF_D` | byte-identical to D: post-reorg copy | delete-candidate |
| `DUPE_EXTERNAL` | non-keeper copy within/across externals | delete-candidate |
| `MEDIA` | year/project parsed; personal vs client; fastwork mapping | copy |
| `RECORDS` | subcategory + convention-compliant rename proposed | copy |
| `ARCHIVE_BOX` | profile/backup dump — box kept intact, native layout | copy |
| `JUNK` | installers, caches, temp, zero-byte, OS litter | delete-candidate |
| `UNKNOWN` | ambiguity — grouped in the decision list | hold |

WD-backup lessons are encoded: `History`-style version stores and `AppData`
mark archive boxes and junk-within-box, but content that is **not** proven
duplicated elsewhere is flagged *sole survivor* and never classified junk.
Duplicate-group keepers keep their content class with keeper status noted.
NAS tiers: recently-modified client projects → `fastwork`
(`<Project>\01_RAW|02_SELECTS|03_EDIT|04_DELIVERABLES`); legacy media,
personal shoots, records, archive boxes → `hdd-mirror`; dupes/junk → `none`.

## Cross-drive comparison and closing its gap

Each drive is triaged into its OWN folder (`C:\DEV\triage\<NAME>\`), because
several physical drives can share a letter — five of this fleet's were all
`F:`. Two commands then work across those folders:

```bat
python -m triage crossdrive --workspace C:\DEV\triage    rem Compare All Drives.bat
python -m triage hashgaps   --workspace C:\DEV\triage    rem Close the Gap.bat
```

`crossdrive` compares the SHA256s the per-drive runs already recorded — it
reads no drive, so nothing needs to be plugged in. Matches are byte-certain;
what it reports is **presence, never absence**. Because each run built its
own size census, a file whose size was unique on its own drive was never
hashed and cannot appear in any comparison. Those files are listed, with the
reason each one has no hash, in `_cross-drive/manifests/cross-drive-gaps.csv`.

`hashgaps` closes exactly that gap: it hashes only the files on that list,
appends the results into the same per-run CSVs, and stops. Attach whichever
drives you can; the rest are named in the summary, and re-running with them
attached continues where it left off. Expect more than one turn per drive —
a file is only worth reading whole once something else in the fleet shares
its 64KB prefix, so a twin pair split across two drives that both mount as
`F:` needs each drive attached twice. The summary always names what still
owes a whole-file hash.

**A drive that no longer holds what it held when it was scanned is refused,
not guessed at.** On Windows the volume label and size stamped beside the
inventory must still match what is mounted at that letter. Then a spread
sample of files that run already hashed is re-read and the hashes must match; samples that are merely
*absent* are disqualifying too, so a sibling drive that shares a few paths
cannot pass on those. The check is repeated before the whole-file pass,
which can start hours later, and every file is re-stat'd so a changed file
is left for the next run rather than recorded against stale metadata. All of
this exists because recording one drive's bytes under another drive's paths
would fabricate a duplicate — the one error that could later justify
deleting the only copy of something.

## The plan stage

```bat
python -m triage plan --workspace C:\DEV\triage    rem Build the Plan.bat
```

Everything before this is analysis; everything after it is the future,
separately approved execution phase. `plan` turns every drive's
classification into ONE ordered plan so the executor never has to reason —
it replays rows in `seq` order and verifies each against the hashes recorded
in the plan:

- **every delete carries byte-certain proof.** A duplicate names its
  keeper's copy row in `depends_on`, and both hashes are recorded, so a
  delete is unreachable until that keeper is on the NAS and verified. A
  delete that cannot be proven is **held**, counted and explained — a delete
  that does not happen costs disk, never data.
- **no two rows share a destination.** Byte-identical sources merge into one
  copy. Different content aimed at one path is qualified with the drive it
  came from (drives are scanned one at a time, so classification cannot see
  the clash); a collision that survives qualification halts the build.
- **a contradiction halts everything.** If classification calls two files
  duplicates but their recorded hashes differ, no plan is written at all:
  `plan-violations.csv` lists every offending row, `plan.csv` is emptied and
  the report replaced, so no stale plan can be executed.
- UNKNOWN/hold rows are never planned — they belong to the decision list.
- **every row names the disk it means.** All six externals mounted as `F:`,
  so a path alone does not identify a file: each row carries the volume
  label and size that drive was inventoried with, and the executor's first
  rule is to confirm that volume is the one present.

## Reproducible classification

The fastwork/hdd-mirror split turns on one date. That date is computed once,
recorded in `activity-cutoff.json` beside the run folders, and reused by
every later `classify` — including the other drives, which are scanned on
different days and would otherwise each get their own. `--cutoff YYYY-MM-DD`
changes it deliberately. Every run folder also carries `run-info.json` (tool
version, cutoff, config, D reference, roots, timestamp) and every report
opens with that provenance line, so a number read months later says which
rules and which date produced it.

Projects are identified by their **directory path**, not their folder name:
two unrelated "Smith Wedding" folders never share an activity timestamp, and
when their names would collide in the destination they are qualified (by
parent folder, else by a stable identity hash) so their same-named camera
files cannot overwrite each other.

## Outputs (all under `output_dir`, default `C:\DEV\triage\`)

```
scope.json                    Phase 0 approval file (you edit this once)
volumes-<stamp>.json          raw volume enumeration
inventory\inventory-<X>.csv   per-drive inventory (path,size,dates,ext,error)
hashes\prefix-<X>.csv         64KB prefix hashes (candidates only)
hashes\full-<X>.csv           full SHA256 (confirmation set only)
classify\classify-<X>.csv     every file: class, evidence, proposal, tier
manifests\manifest-<X>.csv    from → proposed to + new name + NAS tier
reports\report-<X>.md         per-drive triage report
reports\master-plan.md        consolidated plan across all drives
reports\decision-list.md      your judgment calls, grouped for bulk answers
d-hash-request.csv            only if the D: reference lacks hashes
```

The two `.bat` launchers pass `--output-dir C:\DEV\triage\<NAME>`, so in
normal use the tree above exists once **per target** and `C:\DEV\triage\`
itself is the workspace holding them, plus `_cross-drive\` for the
comparison outputs.

Nothing in `manifests\` is executed by this tool — they are input for a
later, separately approved session.

## Testing

```bat
python -m unittest discover -s tests -v
```

99 tests build synthetic fixture drives (media/records/boxes/dupes/junk/
repos), run the full pipeline, and assert classification, resume behavior
(including torn-CSV repair), read-only behavior, cross-drive comparison and
gap closing (including the refusal to hash a drive whose content changed),
and the security properties (no network imports, no delete/rename calls,
guard bypasses).

The Windows-only safety paths (reparse-point skipping, `\\?\` handling,
volume-identity binding, the system-drive output rule) cannot execute on the
Linux build environment, so on Windows do one **first supervised run**
against a small, expendable USB stick and check the log for reparse
warnings and sane paths before pointing the tool at the real drives.

## Known scale characteristics

- Inventory resume holds one set of already-recorded paths in memory:
  roughly 0.5 GB per 2M files during the `inventory` command only.
- Everything else streams; classification memory is proportional to the
  duplicate-candidate set, not the file count.
- The drives are assumed static while triage runs; a file changed
  mid-triage is only re-hashed if its recorded size or mtime changed.
