@echo off
title ID Photo Auto Cropper — Build
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LOG=%~dp0last-build.log"
echo === Build started %date% %time% === > "%LOG%"

echo.
echo ============================================================
echo  BUILD IDPhotoAutoCropper.exe ON THIS PC
echo  First build: about 20-40 minutes. Log: last-build.log
echo ============================================================
echo.

call "%~dp0scripts\ensure_python.bat"
if errorlevel 1 goto :failed
call "%~dp0scripts\ensure_venv.bat" dev
if errorlevel 1 goto :failed
set "PY=.venv\Scripts\python.exe"

echo [1/9] Syncing version...
"%PY%" packaging\sync_version.py >> "%LOG%" 2>&1 || goto :failed

echo [2/9] Running tests...
"%PY%" -m pytest -q >> "%LOG%" 2>&1 || goto :failed

echo [3/9] Cleaning old build...
if exist build rmdir /s /q build
if exist "dist\ID Photo Auto Cropper" rmdir /s /q "dist\ID Photo Auto Cropper"
if exist "dist\portable" rmdir /s /q "dist\portable"
if exist "dist\installer" rmdir /s /q "dist\installer"

echo [4/9] PyInstaller folder build...
"%PY%" -m PyInstaller --noconfirm packaging\pyinstaller.spec >> "%LOG%" 2>&1 || goto :failed

echo [5/9] PyInstaller portable .exe...
"%PY%" -m PyInstaller --noconfirm packaging\pyinstaller-onefile.spec >> "%LOG%" 2>&1 || goto :failed

if not exist "dist\IDPhotoAutoCropper.exe" (
    echo ERROR: dist\IDPhotoAutoCropper.exe was not created.
    goto :failed
)
if not exist "dist\portable" mkdir "dist\portable"
move /Y "dist\IDPhotoAutoCropper.exe" "dist\portable\IDPhotoAutoCropper.exe" >> "%LOG%" 2>&1

set "EXE=dist\ID Photo Auto Cropper\ID Photo Auto Cropper.exe"
set "PORTABLE=dist\portable\IDPhotoAutoCropper.exe"
if not exist "%EXE%" (
    echo ERROR: Missing "%EXE%"
    goto :failed
)

echo [6/9] Selftest folder build...
"%EXE%" --selftest >> "%LOG%" 2>&1 || goto :failed

echo [7/9] Selftest portable build...
"%PORTABLE%" --selftest >> "%LOG%" 2>&1 || goto :failed

echo [8/9] Building installer (Inno Setup)...
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" packaging\installer.iss >> "%LOG%" 2>&1 || goto :failed
    echo Installer created: dist\installer\IDPhotoAutoCropper-Setup.exe
) else (
    echo NOTE: Inno Setup not installed — skipped installer.
    echo Install from https://jrsoftware.org/isinfo.php to also build Setup.exe
)

echo.
echo ============================================================
echo  BUILD SUCCESSFUL
echo.
echo  Portable single file:
echo    dist\portable\IDPhotoAutoCropper.exe
if defined ISCC (
    echo.
    echo  Windows installer:
    echo    dist\installer\IDPhotoAutoCropper-Setup.exe
)
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo BUILD FAILED — open last-build.log in Notepad for details.
call "%~dp0scripts\show_error.bat" build
exit /b 1
