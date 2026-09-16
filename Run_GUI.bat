@echo off
:: Windows Launcher for AudiZap GUI
title AudiZap Music Downloader
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

if exist "venv\Scripts\python.exe" (
    start "" "venv\Scripts\python.exe" gui.py
) else (
    start "" python gui.py
)
exit /b 0
