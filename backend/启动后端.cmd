@echo off
start "Libra Backend" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start_backend.ps1"
exit /b 0

