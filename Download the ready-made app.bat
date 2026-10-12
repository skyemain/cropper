@echo off
title ID Photo Auto Cropper — Download
cd /d "%~dp0"
echo.
echo  This folder is SOURCE CODE — it does not include IDPhotoAutoCropper.exe.
echo.
echo  Opening the download page in your browser...
echo  Download:  IDPhotoAutoCropper-Setup.exe  (recommended)
echo  Or:        IDPhotoAutoCropper.exe         (portable, single file)
echo.
start "" "https://github.com/skyemain/cropper/releases/latest"
echo.
echo  After download, double-click the Setup file to install.
echo  You do NOT need this zip folder anymore.
echo.
pause
