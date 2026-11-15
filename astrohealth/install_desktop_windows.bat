@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python bootstrap_desktop.py %*
) else (
  py -3 bootstrap_desktop.py %*
)
if errorlevel 1 echo Setup failed. See the message above. Python 3.10+ and internet access are needed for first-time setup.
pause
