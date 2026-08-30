<#
.SYNOPSIS
  Phase 0 fallback: list attached volumes (letter, label, size, used, bus)
  without Python. STRICTLY READ-ONLY - only CIM/storage queries, no writes
  to any drive, no network.

.NOTES
  Output: a table on the console and volumes.json next to -OutDir (default
  C:\DEV\triage). Review the list, then approve scope in scope.json (created
  by `python -m triage enumerate`) or pass drives with --drive.
#>
[CmdletBinding()]
param(
    [string]$OutDir = "C:\DEV\triage"
)
Set-StrictMode -Version 2
$ErrorActionPreference = "Stop"

$vols = Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
    $v = $_
    $part = Get-Partition -DriveLetter $v.DriveLetter -ErrorAction SilentlyContinue
    $disk = $null
    if ($part) {
        $disk = Get-Disk -Number $part.DiskNumber -ErrorAction SilentlyContinue
    }
    [pscustomobject]@{
        letter     = "$($v.DriveLetter):"
        label      = $v.FileSystemLabel
        fs         = $v.FileSystem
        size_gb    = [math]::Round($v.Size / 1GB, 2)
        used_gb    = [math]::Round(($v.Size - $v.SizeRemaining) / 1GB, 2)
        free_gb    = [math]::Round($v.SizeRemaining / 1GB, 2)
        bus        = if ($disk) { "$($disk.BusType)" } else { "" }
        model      = if ($disk) { "$($disk.FriendlyName)" } else { "" }
        drive_type = "$($v.DriveType)"
        default_in_scope = -not (
            "$($v.DriveLetter):" -in @("C:", "D:") -or
            "$($v.DriveType)" -eq "Network"
        )
    }
}

$vols | Format-Table letter, label, fs, size_gb, used_gb, bus, drive_type,
    model, default_in_scope -AutoSize

# Never write onto a drive that may be triaged: refuse -OutDir on any
# removable/USB volume or a volume that is in the default scan scope.
$outDrive = ([System.IO.Path]::GetFullPath($OutDir).Substring(0, 2)).ToUpper()
$outVol = $vols | Where-Object { $_.letter -eq $outDrive }
if ($outVol -and ($outVol.default_in_scope -or
        $outVol.bus -eq "USB" -or $outVol.drive_type -eq "Removable")) {
    throw ("REFUSING: -OutDir $OutDir is on $outDrive, a drive this triage " +
           "may scan. Point -OutDir at the system drive (e.g. C:\DEV\triage).")
}

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$json = Join-Path $OutDir "volumes.json"
$vols | ConvertTo-Json -Depth 3 | Set-Content -Path $json -Encoding UTF8
Write-Host "`nWrote $json"
Write-Host "C:, D: and network mounts are excluded by default. Approve the"
Write-Host "final scope via scope.json (python -m triage enumerate) before"
Write-Host "running the triage."
