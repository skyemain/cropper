@echo off
REM Run ID Photo Auto Cropper from source (development mode).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    where py >nul 2>nul && (py -3.11 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv) || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo ERROR: Could not create a virtual environment. Install Python 3.11 or 3.12 first.
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" main.py %*
