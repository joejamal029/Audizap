# Windows Launcher for Spotify & Music Pipeline GUI
@echo off
title Music Pipeline Downloader
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe gui.py
) else (
    python gui.py
)
pause
