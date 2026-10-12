@echo off
title ID Photo Auto Cropper (from source)
setlocal
cd /d "%~dp0"

echo Log file: %~dp0last-run.log
echo === Run started %date% %time% === > "%~dp0last-run.log"

call "%~dp0scripts\ensure_python.bat" >> "%~dp0last-run.log" 2>&1
if errorlevel 1 (
    call "%~dp0scripts\show_error.bat" run
    exit /b 1
)

call "%~dp0scripts\ensure_venv.bat" >> "%~dp0last-run.log" 2>&1
if errorlevel 1 (
    call "%~dp0scripts\show_error.bat" run
    exit /b 1
)

echo Starting ID Photo Auto Cropper... >> "%~dp0last-run.log"
".venv\Scripts\python.exe" main.py %*
if errorlevel 1 (
    echo Application exited with an error. >> "%~dp0last-run.log"
    call "%~dp0scripts\show_error.bat" run
    exit /b 1
)
exit /b 0
