@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python launch_desktop.py %*
) else (
  py -3 launch_desktop.py %*
)
pause
