"""Phase 0: enumerate attached volumes (read-only) and build the scope file.

On Windows this shells out to PowerShell with a fixed, argument-free command
(Get-CimInstance / Get-Volume / Get-Partition - all read-only CIM queries) and
parses its JSON. On other platforms (used for testing this tool) it parses
`lsblk -J -b`. Nothing here writes to any drive.

Output: <output_dir>/volumes-<stamp>.json plus a human-readable table, and a
scope template the user edits/approves to select in-scope drives.
"""

import json
import os
import re
import subprocess

from .util import IS_WINDOWS, atomic_write_json, fmt_gb, now_stamp

# Fixed command strings - never built from user input.
_PS_COMMAND = r"""
$vols = Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
  $v = $_
  $part = Get-Partition -DriveLetter $v.DriveLetter -ErrorAction SilentlyContinue
  $disk = if ($part) { Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue }
  [pscustomobject]@{
    letter   = "$($v.DriveLetter):"
    label    = $v.FileSystemLabel
    fs       = $v.FileSystem
    size     = [int64]$v.Size
    free     = [int64]$v.SizeRemaining
    bus      = if ($disk) { "$($disk.BusType)" } else { "" }
    model    = if ($disk) { "$($disk.FriendlyName)" } else { "" }
    drivetype= "$($v.DriveType)"
  }
}
$vols | ConvertTo-Json -Depth 3
"""


def _enumerate_windows(logger):
    for shell in ("powershell", "pwsh"):
        try:
            proc = subprocess.run(
                [shell, "-NoProfile", "-NonInteractive", "-Command", _PS_COMMAND],
                capture_output=True, text=True, timeout=120, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("volume enumeration via %s failed: %s", shell, exc)
            continue
        if proc.returncode != 0:
            logger.warning("%s exited %d: %s", shell, proc.returncode,
                           proc.stderr[:2000])
            continue
        raw = proc.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return [_normalize_win(v) for v in data]
    raise SystemExit("Could not run PowerShell for volume enumeration.")


def _normalize_win(v):
    return {
        "letter": v.get("letter", ""),
        "label": v.get("label", "") or "",
        "fs": v.get("fs", "") or "",
        "size_bytes": int(v.get("size") or 0),
        "free_bytes": int(v.get("free") or 0),
        "bus": v.get("bus", "") or "",
        "model": v.get("model", "") or "",
        "drive_type": v.get("drivetype", "") or "",
    }


def _enumerate_linux(logger):
    """Test-environment fallback so the tool is exercisable off-Windows."""
    try:
        proc = subprocess.run(
            ["lsblk", "-J", "-b", "-o",
             "NAME,LABEL,FSTYPE,SIZE,MOUNTPOINT,TRAN,MODEL,TYPE"],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except FileNotFoundError:
        logger.warning("lsblk unavailable; returning empty volume list")
        return []
    if proc.returncode != 0:
        logger.warning("lsblk exited %d: %s", proc.returncode, proc.stderr[:500])
        return []
    vols = []

    def visit(node, tran, model):
        tran = node.get("tran") or tran
        model = node.get("model") or model
        if node.get("mountpoint"):
            vols.append({
                "letter": node["mountpoint"],
                "label": node.get("label") or "",
                "fs": node.get("fstype") or "",
                "size_bytes": int(node.get("size") or 0),
                "free_bytes": 0,
                "bus": tran or "",
                "model": (model or "").strip(),
                "drive_type": node.get("type") or "",
            })
        for child in node.get("children", []):
            visit(child, tran, model)

    for dev in json.loads(proc.stdout).get("blockdevices", []):
        visit(dev, "", "")
    return vols


def default_in_scope(vol):
    """Default exclusions: C:, D:, network mounts. Everything else proposed."""
    letter = vol["letter"].upper().rstrip("\\")
    if letter in ("C:", "D:"):
        return False
    if vol["drive_type"].lower() in ("network", "cd-rom", "cdrom"):
        return False
    if vol["bus"].lower() in ("file backed virtual",):
        return False
    return True


def format_table(vols):
    lines = [
        f"{'LETTER':8} {'LABEL':18} {'FS':6} {'SIZE':>10} {'FREE':>10} "
        f"{'BUS':10} {'TYPE':8} MODEL",
        "-" * 92,
    ]
    for v in vols:
        lines.append(
            f"{v['letter']:8} {v['label'][:18]:18} {v['fs']:6} "
            f"{fmt_gb(v['size_bytes']):>10} {fmt_gb(v['free_bytes']):>10} "
            f"{v['bus'][:10]:10} {v['drive_type'][:8]:8} {v['model']}"
        )
    return "\n".join(lines)


def run_enumerate(cfg, logger):
    vols = _enumerate_windows(logger) if IS_WINDOWS else _enumerate_linux(logger)
    stamp = now_stamp()
    out = os.path.join(cfg["output_dir"], f"volumes-{stamp}.json")
    scope_path = os.path.join(cfg["output_dir"], "scope.json")
    atomic_write_json(out, vols)

    proposal = {
        "_instructions": (
            "Phase 0 scope approval. Review in_scope, flip entries as needed, "
            "then re-run with this file. C:, D: and network mounts are "
            "excluded by default and should stay excluded."
        ),
        "volumes": [
            {**v, "in_scope": default_in_scope(v)} for v in vols
        ],
    }
    if not os.path.exists(scope_path):
        atomic_write_json(scope_path, proposal)
    logger.info("enumerated %d volumes -> %s", len(vols), out)
    return vols, scope_path


def load_approved_scope(scope_path):
    with open(scope_path, "r", encoding="utf-8") as fh:
        scope = json.load(fh)
    roots = []
    for v in scope.get("volumes", []):
        if not v.get("in_scope"):
            continue
        letter = v["letter"]
        if re.fullmatch(r"[A-Za-z]:", letter):
            letter += "\\"
        roots.append(letter)
    forbidden = {r.upper().rstrip("\\/") for r in roots} & {"C:", "D:"}
    if forbidden:
        raise SystemExit(
            f"scope.json marks {sorted(forbidden)} in scope. C: and D: are "
            f"excluded from triage by design; edit scope.json.")
    return roots
