@echo off
REM Creates .venv and installs requirements.txt if needed. Requires PY from ensure_python.bat
setlocal
cd /d "%~dp0\.."
if not defined PY (
    echo ERROR: ensure_venv.bat requires PY to be set. Call ensure_python.bat first.
    exit /b 1
)

if exist ".venv\Scripts\python.exe" exit /b 0

echo Creating virtual environment in .venv ...
%PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Could not create .venv — try running this window as Administrator once,
    echo or install Python again with "Add to PATH" enabled.
    exit /b 1
)

echo Installing dependencies (first time only — several minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
set "REQ=requirements.txt"
if /i "%~1"=="dev" set "REQ=requirements-dev.txt"
".venv\Scripts\python.exe" -m pip install -r %REQ%
if errorlevel 1 exit /b 1
exit /b 0
