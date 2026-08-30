# Security profile — drive-triage v1.0.0

Deliverable 5 of the triage mission: what this system reads and writes, its
network posture, where logs/manifests live, risks of running against
removable media, and mitigations. Written to conservative best practice;
**verify against `C:\DEV\script-security-policy.md` before first run** (that
file was not reachable from the remote build session).

## What it reads

| Source | Access | Purpose |
|---|---|---|
| In-scope drives (approved in `scope.json`) | `os.scandir`/`stat`, `open(rb)` | inventory metadata; first 64 KB then full-file reads for hash candidates only |
| D: reference inventory CSV | read | duplicate detection vs post-reorg D: |
| `triage-config.json` | read | configuration |
| Volume metadata | PowerShell `Get-Volume`/`Get-Partition`/`Get-Disk` (read-only CIM queries, fixed command string, no user input interpolated) | Phase 0 enumeration |

C: and D: are refused as scan roots even if marked in scope — the scope
loader hard-rejects them.

## What it writes — and what it never writes

Writes go **only** to `output_dir` (default `C:\DEV\triage\`) and `log_dir`
(default `C:\DEV\logs\drive-triage\`): CSVs, JSON state, Markdown reports,
log files. A startup guard refuses to run if either directory lies under any
scan root, so scanned drives are never written — no files, no sidecars, no
state. The tool contains **no** delete/move/rename operations against
scanned paths (`os.remove` exists only for regenerating its own output CSVs;
`shutil` is not imported anywhere — both enforced by `tests/test_triage.py::
SecurityTest`). Manifests are proposals only; nothing is executed.

Residual (unavoidable) effect: reading files may update NTFS last-access
times where atime updates are enabled. No content or mtime changes.

## Network posture

**No network access, confirmed structurally:** the package imports no
network-capable modules (`socket`, `urllib`, `http`, `requests`, `ftplib`,
`smtplib`, `xmlrpc`, … — enforced by an automated test that scans the
source), and its only subprocess calls are the fixed PowerShell/lsblk volume
queries in `volumes.py` (also test-enforced). Standard library only; no
third-party dependencies, so no supply-chain surface. Safe to run with the
network cable pulled — nothing will notice.

## Privilege requirements

Runs as a normal user. No admin rights needed (volume enumeration via
Get-Volume works unprivileged; inaccessible files are recorded as error rows
rather than escalating). Do not run elevated.

## Risks of running against removable media, and mitigations

| Risk | Mitigation |
|---|---|
| Drive disconnects / USB resets mid-scan | every stage is resumable from append-only CSVs (fsync'd flushes, torn-tail tolerant); re-run the same command |
| Flaky reads on aging drives | 3-attempt backoff on file opens; persistent failures become per-file `error` rows, visible in reports, never silent |
| Sleeping/spun-down drives timing out | same retry path; inventory is metadata-only and cheap, hashing touches only dupe candidates |
| Long paths (>260 chars) on old dumps | `\\?\` extended-length paths used for all reads |
| Locked/permission-denied files | recorded as error rows; nothing skipped silently |
| Accidentally scanning the wrong volume | Phase 0 approval file; C:/D:/network mounts excluded by default and C:/D: hard-refused |
| Output landing on a scanned drive | startup guard aborts before any scan |
| Mid-triage modification of a drive by other software | resume identity-checks path+size; stale hashes are recomputed. Best practice: don't write to externals while triage runs |
| Bit-rot/read instability producing wrong dupe verdicts | dupes require full SHA256 equality; a read error can only cause a *missed* dupe (file stays classified by content), never a false delete-candidate |

## Failure modes and their blast radius

Worst case at any interruption point: partial CSVs under `output_dir` and a
partial log — both harmless and resumable. There is no state on the scanned
drives to corrupt. The classify/report stages are pure functions of the
CSVs and can always be re-run.

## Where things live

- Logs: `C:\DEV\logs\drive-triage\triage-<command>-<stamp>.log` (verbose;
  console shows warnings only)
- Manifests/reports/state: `C:\DEV\triage\` (see README output table)
- Nothing is stored on scanned drives; nothing leaves the machine.
