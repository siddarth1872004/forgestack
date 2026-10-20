@echo off
setlocal
cd /d "%~dp0"
echo ForgeStock - Inventory Management
echo Installing dependencies...
python -m pip install --user -r requirements.txt
if errorlevel 1 (
  echo Dependency installation failed. Check Python and network access.
  pause
  exit /b 1
)
echo Starting ForgeStock at http://127.0.0.1:8000
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
