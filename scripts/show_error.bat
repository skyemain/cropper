@echo off
setlocal
set "MODE=%~1"
echo.
echo ============================================================
if /i "%MODE%"=="build" (
    echo  BUILD FAILED
    echo  Read:  INSTALL.txt  section "Build the .exe on this PC"
) else (
    echo  COULD NOT START THE APP
    echo  Read:  INSTALL.txt  section "If .bat files do nothing"
)
echo.
echo  Easiest fix: run "Download the ready-made app.bat"
echo  and install IDPhotoAutoCropper-Setup.exe — no Python needed.
echo.
echo  Details in:  %~dp0..\last-run.log
echo  or:          %~dp0..\last-build.log
echo ============================================================
echo.
pause
