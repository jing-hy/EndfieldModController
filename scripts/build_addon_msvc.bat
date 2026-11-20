@REM SPDX-License-Identifier: AGPL-3.0-only
@echo off
setlocal
cd /d "%~dp0..\reshade_addon"
call build_msvc.bat || exit /b 1
copy /Y build\endfieldmodcontroller.addon ..\dist\endfieldmodcontroller.addon
echo copied to dist\endfieldmodcontroller.addon
