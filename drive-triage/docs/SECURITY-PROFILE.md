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
log files. Guards, all of which run **before** anything is created:

- output/log dirs must not resolve under any scan root — compared on
  canonical real paths (`realpath`), so `\\?\`, UNC, `subst` and junction
  aliases of a scan root are caught too;
- on Windows, output/log dirs must be on the system drive (C:) unless
  `allow_output_off_system_drive` is set;
- for a whole-drive scan root, volume identity (`st_dev`) is checked as
  well, catching differently-spelled paths onto the same volume;
- scan roots resolve first (scope.json included), so a violation aborts
  before even a log file exists; the PowerShell helper applies the same
  refusal to its `-OutDir`.

The walker never traverses NTFS reparse points (junctions, mount points,
symlinks, cloud placeholders): junctions on cloned system disks could
otherwise redirect the scan onto the live machine, loop forever, or list one
physical file under two paths — which would fabricate a false
delete-candidate. Reparse-point files are recorded but never opened (opening
a OneDrive placeholder can trigger a network hydration).

The tool contains **no** delete/move/rename operations against scanned
paths (`os.remove` exists only for regenerating its own output CSVs;
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
| Drive disconnects / USB resets mid-scan | every stage is resumable from append-only CSVs (fsync'd flushes; a torn final line is terminated on reopen so rows can never merge); a `.done` marker is only written after a walk with zero listing failures, and a circuit breaker aborts hashing after 25 consecutive read failures instead of grinding retries for days |
| Partial state consumed downstream | classify refuses to run unless the hash pass completed against the current inventories (fingerprint gate); classify CSVs and manifests are written atomically (temp + replace); report refuses missing classifications |
| Flaky reads on aging drives | 3-attempt backoff on file opens; persistent failures become per-file `error` rows, visible in reports, never silent |
| Sleeping/spun-down drives timing out | same retry path; inventory is metadata-only and cheap, hashing touches only dupe candidates |
| Long paths (>260 chars) on old dumps | `\\?\` extended-length paths (normalized first) for all reads |
| Junctions/mount points on cloned system disks | reparse points are never traversed (scope escape, cycles, and one-file-two-paths false dupes all prevented) |
| Undecodable/surrogate filenames | CSV state round-trips them exactly (`surrogatepass`); logging escapes them; no crash, no wedged resume |
| Locked/permission-denied files | recorded as error rows; nothing skipped silently |
| Accidentally scanning the wrong volume | Phase 0 approval file; C:/D:/network mounts excluded by default; C:/D: hard-refused from every root source (scope, config, --drive); overlapping scan roots refused (they would fabricate self-duplicates); a different physical volume appearing at a known drive letter is detected via a stored label+size signature and refused |
| A D: reference CSV that actually covers a scanned drive | reference entries under any scan root are dropped with a warning (a file can never be an "exact dupe" of itself) |
| Output landing on a scanned drive | startup guards abort before any scan or any write (see above) |
| Mid-triage modification of a drive by other software | resume identity-checks path+size+mtime; stale hashes are recomputed. The triage assumes drives are static while it runs — don't write to externals mid-triage |
| Bit-rot/read instability producing wrong dupe verdicts | dupes require full SHA256 equality; a read error can only cause a *missed* dupe (file stays classified by content), never a false delete-candidate; the elected keeper of a dupe group is never classified junk, so a group can never lose all copies |

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
