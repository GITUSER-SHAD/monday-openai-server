@echo off
setlocal
title Close the Gap
cd /d "%~dp0"
echo.
echo  CLOSE THE GAP
echo  =============
echo.
echo  Hashes ONLY the files the cross-drive comparison could not compare.
echo  Nothing already done is redone, and no drive is written to.
echo.
echo  Plug in whichever drives you can. Several of yours use the same drive
echo  letter, so only one of those can be attached at a time - that is fine.
echo  Any drive that is not attached is named at the end, and running this
echo  again with it plugged in continues from where it stopped.
echo.
echo  Expect to run this more than once. When two files on two drives look
echo  like a match, the second drive has to come back for a whole-file read.
echo  The summary tells you exactly which drives still owe one.
echo.
echo  A drive that is attached but no longer holds what it held when it was
echo  scanned is refused, not guessed at.
echo.
echo  This can run for hours on large video files. Do NOT close this window.
echo  It is done only when you see "Press any key to continue".
echo.
pause
echo.
python -m triage hashgaps --config triage-config.json --workspace "C:\DEV\triage"
echo.
if errorlevel 1 (
  echo ============================================
  echo STOPPED before finishing - see the message
  echo above. No drive was written to. Anything
  echo already hashed is saved; running this again
  echo picks up from there.
  echo ============================================
) else (
  echo ============================================
  echo FINISHED. Read the summary above: it says
  echo what was done and what still needs a drive
  echo attached.
  echo.
  echo Then run "Compare All Drives.bat" to fold
  echo the new hashes into the comparison.
  echo ============================================
)
echo.
pause
