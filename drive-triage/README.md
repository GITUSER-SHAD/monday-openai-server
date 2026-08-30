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
- Per-drive state is independent: a missing drive is skipped at inventory
  with a warning (re-run when it's attached). `hash`/`classify` require the
  in-scope inventories to be complete first and say so if not.

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

Nothing in `manifests\` is executed by this tool — they are input for a
later, separately approved session.

## Testing

```bat
python -m unittest discover -s tests -v
```

48 tests build synthetic fixture drives (media/records/boxes/dupes/junk/
repos), run the full pipeline, and assert classification, resume behavior
(including torn-CSV repair), read-only behavior, and the security
properties (no network imports, no delete/rename calls, guard bypasses).

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
