@echo off
setlocal
cd /d "%~dp0"
if exist "dist\Mirage\Mirage.exe" (
  start "Mirage" "dist\Mirage\Mirage.exe"
  exit /b 0
)
if exist ".venv\Scripts\pythonw.exe" (
  start "Mirage" ".venv\Scripts\pythonw.exe" -m mirage
  exit /b 0
)
echo Python environment was not found. Run tools\setup.ps1 first.
pause
