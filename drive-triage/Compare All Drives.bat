@echo off
setlocal
title Cross-Drive Comparison
cd /d "%~dp0"
echo.
echo  CROSS-DRIVE COMPARISON
echo  ======================
echo.
echo  Compares every drive already triaged, using the hashes those scans
echo  already recorded. No drive is read - nothing needs to be plugged in.
echo.
python -m triage crossdrive --config triage-config.json --workspace "C:\DEV\triage"
echo.
if errorlevel 1 (
  echo ============================================
  echo FAILED - see the error message above.
  echo ============================================
) else (
  echo ============================================
  echo DONE. Report is in
  echo C:\DEV\triage\_cross-drive\reports\
  echo ============================================
)
echo.
pause
