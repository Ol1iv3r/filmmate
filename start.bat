@echo off
rem Double-click this file to start Filmmate (backend + frontend).
rem Close the window that opens to stop both.
cd /d "%~dp0"
start "Filmmate" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-filmmate.ps1"
