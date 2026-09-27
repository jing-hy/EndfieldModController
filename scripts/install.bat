@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv || goto :error
)
echo Installing requirements...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
echo Installation complete.
echo Run: run.bat
exit /b 0
:error
echo Installation failed.
pause
exit /b 1
