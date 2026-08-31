@echo off
setlocal
title Drive Triage
cd /d "%~dp0"
echo.
echo  DRIVE TRIAGE
echo  ============
echo.
echo  Enter EITHER a drive letter (example: F)
echo  OR a network path      (example: \\100.76.11.114\fastwork)
echo.
set /p TARGET="Target, then Enter: "
echo.
echo  Name this target - used for its report folder, so two drives that
echo  share a letter never overwrite each other (example: NAS_fastwork)
echo.
set /p NAME="Name for this target, then Enter: "
echo.
echo  Have you DELETED files from this target since it was last scanned?
echo  (Answer Y to re-check the file list so deletions drop out. Hashes
echo   already computed are kept, so this stays fast. Answer N or just
echo   press Enter for a normal run.)
echo.
set "REFRESH="
set /p ANSWER="Deleted files since last scan? (y/N): "
if /i "%ANSWER%"=="y" set "REFRESH=--refresh"
echo.
if "%TARGET:~1%"=="" vol %TARGET%:
echo.
echo Checking the target is reachable...
python -m triage probe --config triage-config.json --drive "%TARGET%"
if errorlevel 1 (
  echo.
  echo ============================================
  echo CANNOT REACH THE TARGET - nothing was scanned.
  echo See the message above.
  echo ============================================
  echo.
  pause
  exit /b 1
)
echo.
echo ============================================
echo Above is what will be scanned. If that looks
echo wrong, close this window now to cancel.
echo ============================================
echo.
pause
echo.
echo Running triage on %TARGET% as "%NAME%" ...
echo (This can sit with no new text for several minutes on a big target -
echo  that is normal. Do NOT close this window. It is done only when you
echo  see "Press any key to continue" below.)
echo.
python -m triage all --config triage-config.json --drive "%TARGET%" --output-dir "C:\DEV\triage\%NAME%" %REFRESH%
echo.
if errorlevel 1 (
  echo ============================================
  echo FAILED - see the error message above.
  echo Nothing on %TARGET% was touched. Send this
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
