@echo off
REM ============================================================
REM  ID Photo Auto Cropper - Windows build script
REM  Creates dist\ID Photo Auto Cropper\ID Photo Auto Cropper.exe
REM  and (when Inno Setup is installed) IDPhotoAutoCropper-Setup.exe
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo [1/7] Preparing Python virtual environment...
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul && (py -3.11 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv) || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Could not create a virtual environment. Install Python 3.11 or 3.12 from python.org first.
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"

echo.
echo [2/7] Installing pinned dependencies...
"%PY%" -m pip install --upgrade pip --quiet || goto :fail
"%PY%" -m pip install -r requirements-dev.txt --quiet || goto :fail

echo.
echo [3/7] Running the automated test suite...
"%PY%" -m pytest || goto :fail

echo.
echo [4/7] Cleaning previous build output...
if exist build rmdir /s /q build
if exist "dist\ID Photo Auto Cropper" rmdir /s /q "dist\ID Photo Auto Cropper"

echo.
echo [5/7] Building the one-folder Windows application (PyInstaller)...
"%PY%" -m PyInstaller --noconfirm packaging\pyinstaller.spec || goto :fail

echo.
echo [6/7] Verifying the packaged application...
set "EXE=dist\ID Photo Auto Cropper\ID Photo Auto Cropper.exe"
if not exist "%EXE%" (
    echo ERROR: expected executable not found: %EXE%
    goto :fail
)
if not exist "dist\ID Photo Auto Cropper\_internal\models\face_landmarker.task" (
    echo ERROR: bundled MediaPipe model missing from the build.
    goto :fail
)
if not exist "dist\ID Photo Auto Cropper\_internal\assets\icon.ico" (
    echo ERROR: bundled assets missing from the build.
    goto :fail
)
"%EXE%" --selftest
if errorlevel 1 (
    echo ERROR: packaged application selftest FAILED. Check %%APPDATA%%\IDPhotoAutoCropper\app.log
    goto :fail
)
echo Packaged application selftest passed.

echo.
echo [7/7] Building the installer (optional, requires Inno Setup)...
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" packaging\installer.iss || goto :fail
    echo Installer created: dist\installer\IDPhotoAutoCropper-Setup.exe
) else (
    echo Inno Setup not found - skipping installer. Install it from https://jrsoftware.org/isinfo.php
    echo and re-run this script to also produce IDPhotoAutoCropper-Setup.exe
)

echo.
echo ============================================================
echo  BUILD SUCCESSFUL
echo  Application folder : dist\ID Photo Auto Cropper\
echo  Executable         : dist\ID Photo Auto Cropper\ID Photo Auto Cropper.exe
if defined ISCC echo  Installer          : dist\installer\IDPhotoAutoCropper-Setup.exe
echo ============================================================
exit /b 0

:fail
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
