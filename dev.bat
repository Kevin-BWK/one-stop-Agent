@echo off
rem One-click dev launcher (backend + frontend H5), then opens the browser.
rem Usage: dev.bat          start
rem        dev.bat -Stop    stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
if errorlevel 1 pause
