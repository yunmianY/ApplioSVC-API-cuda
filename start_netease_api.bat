@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

where NeteaseCloudMusicApi >nul 2>nul
if errorlevel 1 (
  echo [INFO] NeteaseCloudMusicApi not found, installing globally ...
  call npm install -g NeteaseCloudMusicApi@4.32.0 --registry=https://registry.npmmirror.com
  if errorlevel 1 (
    echo [ERROR] npm install failed. Check your network / nodejs installation.
    pause
    exit /b 1
  )
)

echo ============================================================
echo   NeteaseCloudMusicApi  (needed by VIP downloads)
echo   Listening on http://127.0.0.1:3000
echo   Keep this window open. Close it to stop the service.
echo ============================================================
echo.
NeteaseCloudMusicApi %*
echo.
echo NeteaseCloudMusicApi stopped.
pause
