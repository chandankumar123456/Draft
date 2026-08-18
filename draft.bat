@echo off
rem Launcher script for Draft Developer Cockpit
set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

if exist "%PROJECT_ROOT%draft_venv\Scripts\python.exe" (
    "%PROJECT_ROOT%draft_venv\Scripts\python.exe" run_tui.py %*
) else (
    python run_tui.py %*
)
