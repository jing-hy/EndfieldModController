@echo off
setlocal
set RESHADE_INCLUDE=%~dp0vendor\reshade\include
set IMGUI_INCLUDE=%~dp0vendor\imgui
if not exist build mkdir build
cl /nologo /std:c++17 /LD /EHsc /W3 /DWIN32_LEAN_AND_MEAN /DNOMINMAX /D_CRT_SECURE_NO_WARNINGS ^
  /I"%RESHADE_INCLUDE%" /I"%IMGUI_INCLUDE%" ^
  src\endfieldmodcontroller_addon.cpp ^
  /Fe:build\endfieldmodcontroller.addon ^
  /link user32.lib kernel32.lib
echo built: %~dp0build\endfieldmodcontroller.addon
