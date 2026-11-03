@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
setlocal
cd /d "%~dp0"

set "PYTHON="
if exist "..\ApplioV3.6.5\env\python.exe" set "PYTHON=..\ApplioV3.6.5\env\python.exe"
if not defined PYTHON if exist "..\Applio\env\python.exe" set "PYTHON=..\Applio\env\python.exe"
if not defined PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON=python"
)
if not defined PYTHON (
  echo [ERROR] Python not found. Run install_env.bat first.
  pause
  exit /b 1
)

title ApplioSVC-API - SVC gateway (9999)
echo Starting SVC-compatible gateway at http://127.0.0.1:9999/
echo Note: this gateway maps the SVC parameter contract onto Applio models,
echo it is NOT an SVC-Fusion upstream.
echo.
"%PYTHON%" app_svc.py %*
echo.
echo Server stopped.
pause
