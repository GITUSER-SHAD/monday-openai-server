"""drive-triage: read-only external drive triage system.

Phases:
  0  enumerate  - list attached volumes, write scope file for approval
  1  inventory  - per-drive full file inventory -> CSV (resumable)
     hash       - two-stage duplicate detection (size + 64KB prefix, SHA256 confirm)
  2  classify   - every file -> exact-D-dupe / external-dupe / media / records /
                  archive-box / junk / unknown
  3  report     - per-drive reports, master plan, move manifests, decision list

STRICTLY READ-ONLY with respect to scanned drives: the package never writes,
renames, deletes, or modifies anything under a scan root. All outputs go to
the configured output/log directories, which are validated to be outside
every scan root.
"""

__version__ = "1.0.0"
