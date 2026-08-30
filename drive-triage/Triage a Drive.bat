@echo off
setlocal
title Drive Triage
echo.
echo  DRIVE TRIAGE
echo  ============
echo.
set /p DRIVE="Enter the drive letter to triage (example: F), then press Enter: "
echo.
echo Running triage on %DRIVE%: ...
echo (This can sit with no new text for several minutes on a big drive -
echo  that is normal. Do NOT close this window. It is done only when you
echo  see "Press any key to continue" below.)
echo.
cd /d "%~dp0"
python -m triage all --config triage-config.json --drive %DRIVE%:\
echo.
if errorlevel 1 (
  echo ============================================
  echo FAILED - see the error message above.
  echo Nothing on %DRIVE%: was touched. Send this
  echo window's text to Claude to fix it.
  echo ============================================
) else (
  echo ============================================
  echo DONE. Reports are in C:\DEV\triage\reports\
  echo ============================================
)
echo.
pause
