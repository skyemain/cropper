@echo off
REM ============================================================
REM  BUILD SCRIPT (developers only — end users never run this)
REM
REM  Produces two downloads for Windows users:
REM    dist\installer\IDPhotoAutoCropper-Setup.exe   (recommended)
REM    dist\portable\IDPhotoAutoCropper.exe          (copy anywhere)
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo [1/9] Preparing Python virtual environment...
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>nul && (py -3.11 -m venv .venv 2>nul || py -3.12 -m venv .venv 2>nul || py -3 -m venv .venv) || python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Could not create a virtual environment. Install Python 3.11 or 3.12 from python.org first.
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"

echo.
echo [2/9] Installing pinned dependencies...
"%PY%" -m pip install --upgrade pip --quiet || goto :fail
"%PY%" -m pip install -r requirements-dev.txt --quiet || goto :fail

echo.
echo [3/9] Syncing installer version from app\__init__.py...
"%PY%" packaging\sync_version.py || goto :fail

echo.
echo [4/9] Running the automated test suite...
"%PY%" -m pytest -q || goto :fail

echo.
echo [5/9] Cleaning previous build output...
if exist build rmdir /s /q build
if exist "dist\ID Photo Auto Cropper" rmdir /s /q "dist\ID Photo Auto Cropper"
if exist "dist\portable" rmdir /s /q "dist\portable"
if exist "dist\installer" rmdir /s /q "dist\installer"

echo.
echo [6/9] Building the installed app folder (PyInstaller one-folder)...
"%PY%" -m PyInstaller --noconfirm packaging\pyinstaller.spec || goto :fail

echo.
echo [7/9] Building the portable single-file .exe...
"%PY%" -m PyInstaller --noconfirm packaging\pyinstaller-onefile.spec || goto :fail
if not exist "dist\IDPhotoAutoCropper.exe" goto :fail_portable
if not exist "dist\portable" mkdir "dist\portable"
move /Y "dist\IDPhotoAutoCropper.exe" "dist\portable\IDPhotoAutoCropper.exe" >nul

echo.
echo [8/9] Verifying packaged builds...
set "EXE=dist\ID Photo Auto Cropper\ID Photo Auto Cropper.exe"
set "PORTABLE=dist\portable\IDPhotoAutoCropper.exe"
if not exist "%EXE%" (
    echo ERROR: expected executable not found: %EXE%
    goto :fail
)
if not exist "dist\ID Photo Auto Cropper\_internal\models\face_landmarker.task" (
    echo ERROR: bundled MediaPipe model missing from the folder build.
    goto :fail
)
"%EXE%" --selftest || goto :fail
echo Folder build selftest passed.
"%PORTABLE%" --selftest || goto :fail
echo Portable build selftest passed.

echo.
echo [9/9] Building the Windows installer (Inno Setup)...
set "ISCC="
where iscc >nul 2>nul && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC (
    "%ISCC%" packaging\installer.iss || goto :fail
    echo Installer created: dist\installer\IDPhotoAutoCropper-Setup.exe
) else (
    echo WARNING: Inno Setup not found — skipping installer.
    echo Install from https://jrsoftware.org/isinfo.php and re-run this script.
)

echo.
echo ============================================================
echo  BUILD SUCCESSFUL — give users ONE of these files:
echo.
echo  RECOMMENDED (install + uninstall + easy updates):
echo    dist\installer\IDPhotoAutoCropper-Setup.exe
echo.
echo  PORTABLE (copy single .exe anywhere, no install):
echo    dist\portable\IDPhotoAutoCropper.exe
echo.
echo  See INSTALL.txt for end-user instructions.
echo ============================================================
exit /b 0

:fail_portable
echo ERROR: portable executable was not produced.
goto :fail

:fail
echo.
echo BUILD FAILED - see the messages above.
exit /b 1
