@echo off
setlocal
title Drive Triage
echo.
echo  DRIVE TRIAGE
echo  ============
echo.
set /p DRIVE="Drive letter to triage (example: F), then Enter: "
echo.
echo  Name this drive - used for its report folder, so two drives that
echo  share a letter never overwrite each other (example: Samsung_T5)
echo.
set /p NAME="Name for this drive, then Enter: "
echo.
vol %DRIVE%:
echo.
echo Running triage on %DRIVE%: as "%NAME%" ...
echo (This can sit with no new text for several minutes on a big drive -
echo  that is normal. Do NOT close this window. It is done only when you
echo  see "Press any key to continue" below.)
echo.
cd /d "%~dp0"
python -m triage all --config triage-config.json --drive %DRIVE%:\ --output-dir "C:\DEV\triage\%NAME%"
echo.
if errorlevel 1 (
  echo ============================================
  echo FAILED - see the error message above.
  echo Nothing on %DRIVE%: was touched. Send this
  echo window's text to Claude to fix it.
  echo ============================================
) else (
  echo ============================================
  echo DONE. Reports are in
  echo C:\DEV\triage\%NAME%\reports\
  echo ============================================
)
echo.
pause
