@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Please install Python 3.10 or newer from python.org, then run this file again.
  pause
  exit /b 1
)
python server.py
pause
