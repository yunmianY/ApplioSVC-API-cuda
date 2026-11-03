@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
cd /d "%~dp0"

echo ============================================================
echo   ApplioSVC-API one-click launcher
echo   1) NeteaseCloudMusicApi :3000  (VIP song downloads)
echo   2) ApplioSVC-API        :3333  (cover gateway)
echo ============================================================
echo.

where NeteaseCloudMusicApi >nul 2>nul
if errorlevel 1 (
  echo [1/3] NeteaseCloudMusicApi not found, installing globally ...
  call npm install -g NeteaseCloudMusicApi@4.32.0 --registry=https://registry.npmmirror.com
  if errorlevel 1 (
    echo [WARN] npm install failed, VIP downloads will not work.
  )
) else (
  echo [1/3] NeteaseCloudMusicApi is installed.
)

echo [2/3] Starting NeteaseCloudMusicApi in a new window (port 3000) ...
start "NeteaseCloudMusicApi - keep this window open" cmd /k NeteaseCloudMusicApi
timeout /t 8 /nobreak >nul

set "PYTHON="
if exist "..\ApplioV3.6.5\env\python.exe" set "PYTHON=..\ApplioV3.6.5\env\python.exe"
if not defined PYTHON if exist "..\Applio\env\python.exe" set "PYTHON=..\Applio\env\python.exe"
if not defined PYTHON set "PYTHON=python"

echo [3/3] Starting ApplioSVC-API on http://127.0.0.1:3333 ...
echo       Interpreter: %PYTHON%
echo.
"%PYTHON%" app_rvc.py %*
echo.
echo ApplioSVC-API stopped.
pause
