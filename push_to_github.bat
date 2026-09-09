@echo off
REM Push this project to GitHub (run once after creating the repo).
REM Requires: Git for Windows, and GitHub login (browser or personal access token).
setlocal
cd /d "%~dp0"

set "GITHUB_URL=https://github.com/yeruvavinay/cropper.git"

git remote get-url github >nul 2>nul
if errorlevel 1 (
    git remote add github "%GITHUB_URL%"
) else (
    git remote set-url github "%GITHUB_URL%"
)

echo Pushing branch main to %GITHUB_URL% ...
git push -u github main
if errorlevel 1 (
    echo.
    echo Push failed. If GitHub asks for credentials, use a Personal Access Token
    echo as the password: https://github.com/settings/tokens
    exit /b 1
)

echo.
echo Done. Your code is at https://github.com/yeruvavinay/cropper
exit /b 0
