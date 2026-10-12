@echo off
setlocal EnableDelayedExpansion
set "PY="

py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3.12"
    goto :found
)
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3.11"
    goto :found
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
    goto :found
)

python -c "import sys; v=sys.version_info; exit(0 if (3,11)<=v[:2]<=(3,12) else 1)" >nul 2>&1
if not errorlevel 1 (
    set "PY=python"
    goto :found
)

echo.
echo ERROR: Python 3.11 or 3.12 was not found on this PC.
echo.
echo The ready-made app does NOT require Python. Download instead:
echo   https://github.com/skyemain/cropper/releases
echo   File: IDPhotoAutoCropper-Setup.exe
echo.
echo To run from source code, install Python from https://www.python.org/downloads/
echo During setup, check "Add python.exe to PATH".
echo.
exit /b 1

:found
endlocal & set "PY=%PY%"
exit /b 0
