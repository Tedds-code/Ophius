@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python bootstrap_desktop.py --launch %*
) else (
  py -3 bootstrap_desktop.py --launch %*
)
pause
