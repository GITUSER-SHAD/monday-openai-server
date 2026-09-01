@echo off
setlocal
title Build the Plan
cd /d "%~dp0"
echo.
echo  BUILD THE PLAN
echo  ==============
echo.
echo  Turns every drive's classification into ONE ordered plan: what gets
echo  copied to the NAS, in what order, and which duplicates may then be
echo  deleted. Nothing is executed and no drive is read - this works only
echo  from the CSVs the scans already wrote.
echo.
echo  If any row cannot be PROVEN safe, no plan is written at all and every
echo  problem row is listed instead. That is the intended behaviour.
echo.
pause
echo.
python -m triage plan --config triage-config.json --workspace "C:\DEV\triage"
echo.
if errorlevel 1 (
  echo ============================================
  echo NO PLAN WRITTEN - see the message above.
  echo The problem rows are listed in
  echo C:\DEV\triage\_plan\plan-violations.csv
  echo Nothing was executed and no drive was read.
  echo ============================================
) else (
  echo ============================================
  echo PLAN WRITTEN. Read
  echo C:\DEV\triage\_plan\plan-report.md
  echo Still nothing executed.
  echo ============================================
)
echo.
pause
