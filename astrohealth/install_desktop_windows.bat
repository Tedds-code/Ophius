@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python setup_desktop.py %*
) else (
  py -3 setup_desktop.py %*
)
if errorlevel 1 echo Python 3.10+ is required. Download it from https://www.python.org/downloads/
pause
