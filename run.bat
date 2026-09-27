@echo off
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m endfieldmodcontroller
  ) else (
    start "" pythonw.exe -m endfieldmodcontroller
  )
  exit /b 0
)

set "PY=python"
"%PY%" -c "import webview" >nul 2>nul
if not errorlevel 1 goto :run

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
  goto :run
)

echo Missing dependencies. Running scripts\install.bat ...
call "%~dp0scripts\install.bat"
if errorlevel 1 goto :error
set "PY=.venv\Scripts\python.exe"

:run
"%PY%" -m endfieldmodcontroller %*
if errorlevel 1 goto :pause
exit /b 0

:pause
pause
exit /b 1

:error
echo Launch failed.
pause
exit /b 1
