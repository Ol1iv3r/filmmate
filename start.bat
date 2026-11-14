@echo off
rem Double-click this file to start the Python app and open it in your browser.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-filmmate.ps1"
if errorlevel 1 (
    pause
    exit /b 1
)
