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

title ApplioSVC-API - RVC gateway (3333)
echo Starting RVC-compatible gateway at http://127.0.0.1:3333/
echo Upstream: Applio voice conversion + UVR5 vocal separation
echo.
"%PYTHON%" app_rvc.py %*
echo.
echo Server stopped.
pause
