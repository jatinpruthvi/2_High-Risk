@echo off
REM Daily phase-2 evidence run launcher (Windows Task Scheduler / double-click).
REM Sets the working directory and Fyers credentials, then runs:
REM   tests -> evidence report -> dated archive
REM
REM Schedule with Task Scheduler:
REM   Program:  C:\Windows\System32\cmd.exe
REM   Args:     /c "E:\Jatin-Project\DHAN\1\run_daily_evidence.bat"
REM   Start in: E:\Jatin-Project\DHAN\1
REM   Trigger:  daily, e.g. 18:30 after market close (skip weekends optional)
REM
REM Credentials are read from paper_state\creds.env (gitignored, format:
REM   FYERS_APP_ID=...
REM   FYERS_SECRET_ID=...
REM ) or from the environment if the file is absent. They are only needed if
REM the paper runner is (re)started; the daily evidence run itself reads saved
REM paper_state files, so these are optional but harmless.

cd /d "E:\Jatin-Project\DHAN\1"

if exist "paper_state\creds.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("paper_state\creds.env") do set "%%A=%%B"
)

echo [%date% %time%] daily evidence run starting
python -m institutional_options.daily_evidence_run
set EXIT=%ERRORLEVEL%
echo [%date% %time%] daily evidence run finished with exit code %EXIT%
exit /b %EXIT%
