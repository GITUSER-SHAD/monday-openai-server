@echo off
setlocal
title Re-Classify All Drives
cd /d "%~dp0"
echo.
echo  RE-CLASSIFY ALL DRIVES
echo  ======================
echo.
echo  Re-decides what every file on every drive IS - keep, duplicate, junk -
echo  and where it should go. No drive is read and nothing needs to be
echo  plugged in: this works only from the CSVs the scans already wrote.
echo.
echo  Run this after "Close the Gap" and "Compare All Drives". Those prove
echo  duplicates the earlier classification had to call unique, and until
echo  this runs, the plan would still be built from the old answer.
echo.
echo  Every drive is measured against ONE date, so the split between the
echo  fast working set and the mirror does not move from drive to drive.
echo.
echo  This can take a while on the large drives. Do NOT close this window.
echo  It is done only when you see "Press any key to continue".
echo.
pause
echo.
python -m triage reclassify --config triage-config.json --workspace "C:\DEV\triage"
echo.
if errorlevel 1 (
  echo ============================================
  echo NOT EVERY DRIVE WAS DONE.
  echo.
  echo Read the message above. It either names each
  echo drive that was missed and why, or says no
  echo drive folders were found at all.
  echo.
  echo Any drive that was missed still holds its OLD
  echo classification, so do NOT build the plan yet:
  echo it would mix old answers with new ones.
  echo.
  echo No drive was read and nothing was lost.
  echo ============================================
) else (
  echo ============================================
  echo DONE. Every drive re-classified against the
  echo same date.
  echo.
  echo Now run "Build the Plan.bat".
  echo ============================================
)
echo.
pause
