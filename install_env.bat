@echo off
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   ApplioSVC-API environment setup (CUDA / NVIDIA)
echo ============================================================
echo.

set "PYTHON="
if exist "..\ApplioV3.6.5\env\python.exe" set "PYTHON=..\ApplioV3.6.5\env\python.exe"
if not defined PYTHON if exist "..\Applio\env\python.exe" set "PYTHON=..\Applio\env\python.exe"
if not defined PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
  echo [ERROR] Python not found. Install Python 3.10+ or Applio first.
  pause
  exit /b 1
)

echo [1/4] Interpreter: %PYTHON%
%PYTHON% -c "import sys; print('   Python', sys.version.split()[0])"

echo.
echo [2/4] Checking PyTorch / CUDA
%PYTHON% -c "import torch; print('   torch', torch.__version__, '| cuda', torch.cuda.is_available())"
if errorlevel 1 (
  echo    [!] PyTorch missing, installing CUDA 12.6 build...
  %PYTHON% -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu126
)

echo.
echo [3/4] Installing middleware requirements (Tsinghua mirror)
%PYTHON% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo    [!] pip install failed, check your network or use another mirror.
  pause
  exit /b 1
)

echo.
echo [4/4] Downloading vocal separation model
%PYTHON% tools\download_models.py

echo.
echo Done. Double-click the RVC launcher bat in this folder (port 3333).
pause
