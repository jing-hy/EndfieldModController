@echo off
rem ============================================================================
rem  ModeController - LEGACY 手动工具（不属于当前官方 XXMI/EFMI 路线）
rem  [encoding: GBK/936, Windows cmd]   背景见 docs\历史成功路线-进程内注入.md
rem
rem  作用：复现 2026-09-27 09:31~11:28 那次确认可用的注入链路
rem        migoto_loader2.exe 轮询 Endfield.exe
rem          -> 注入 mc_bootstrap.dll
rem          -> 桥在进程内等 dxgi.dll 就绪后 LoadLibrary runtime\migoto\d3d11.dll
rem          -> d3dx.ini 加载 Core\EFMI\main.ini + Mods\MC_*
rem
rem  前提：游戏必须由官方启动器点「DirectX 11 启动」（D3D12 下不生效）
rem  本脚本只做三件事：恢复被停放的注入器/桥、复制 Mods、启动注入器。
rem  它不改游戏目录、不碰官方 XXMI 安装；还原方法见脚本末尾提示。
rem ============================================================================
setlocal enableextensions
set "ROOT=%~dp0.."
set "MG=%ROOT%\runtime\migoto"
set "STAGE=%ROOT%\runtime\builtin\XXMI\EFMI\Mods"

if not exist "%MG%" (
  echo [X] 找不到 runtime\migoto：%MG%
  pause
  exit /b 1
)

echo [1/5] 检查是否已有官方 XXMI 在运行 ...
set "PROBE=%TEMP%\mc_legacy_probe.txt"
tasklist /FI "IMAGENAME eq XXMI Launcher.exe" > "%PROBE%" 2>nul
findstr /I /C:"XXMI Launcher.exe" "%PROBE%" >nul
if not errorlevel 1 (
  echo     [!] XXMI Launcher 正在运行。
  echo         两条注入链路同时存在会重复 Hook，复现历史路线前请先关掉官方 XXMI/EFMI。
)
del "%PROBE%" >nul 2>&1

echo [2/5] 恢复被停放的注入器与桥 ...
call :restore "%MG%\migoto_loader2.exe"
call :restore "%MG%\mc_bootstrap.dll"
if not exist "%MG%\migoto_loader2.exe" goto :missing
if not exist "%MG%\mc_bootstrap.dll"    goto :missing
if not exist "%MG%\d3d11.dll" (
  echo     [!] 缺少 %MG%\d3d11.dll（EFMI 主 DLL，v1.1.9）
  goto :missing
)

echo [3/5] 写入注入顺序 inject_order.txt = mc_bootstrap.dll ...
> "%MG%\inject_order.txt" echo mc_bootstrap.dll

echo [4/5] 准备 Mods 目录（从 EFMI staging 复制）...
if not exist "%MG%\Mods" mkdir "%MG%\Mods"
if exist "%STAGE%" (
  robocopy "%STAGE%" "%MG%\Mods" /E /NFL /NDL /NJH /NJS >nul
  if errorlevel 8 (
    echo     [!] robocopy 返回 %errorlevel%，请检查 Mods 是否复制完整。
  ) else (
    echo     已同步 Mods：%STAGE%
  )
) else (
  echo     [!] 找不到 staging 目录 %STAGE%，Mods 保持原样。
)

echo [5/5] 启动注入器（独立最小化窗口，最多轮询 300 秒）...
start "ModeController legacy injector" /MIN "%MG%\migoto_loader2.exe"

echo.
echo ============================================================
echo  注入器已启动。现在请：
echo    1) 打开官方启动器
echo    2) 点「DirectX 11 启动」（不要点普通开始按钮）
echo.
echo  约 30 秒后验证：
echo    type "%MG%\mc_bootstrap.log"
echo       期望：loading EFMI dll=...  然后 load result h=... err=0
echo    findstr /C:"Processing" "%MG%\d3d11_log.txt"
echo       期望：Processing "...\Mods\MC_xxx\...ini"
echo    findstr /C:"Loading custom resource" "%MG%\d3d11_log.txt"
echo       期望：Loading custom resource ...\Mods\MC_xxx\...dds as DDS
echo.
echo  还原（不想用了就执行）：
echo    ren "%MG%\migoto_loader2.exe" migoto_loader2.exe.modecontroller.disabled
echo    ren "%MG%\mc_bootstrap.dll"    mc_bootstrap.dll.modecontroller.disabled
echo ============================================================
echo.
pause
exit /b 0

:restore
if exist "%~1" exit /b 0
if exist "%~1.modecontroller.disabled" (
  ren "%~1.modecontroller.disabled" "%~nx1"
  echo     [i] 已恢复 %~nx1
  exit /b 0
)
echo     [!] 既没有 %~nx1，也没有 %~nx1.modecontroller.disabled
exit /b 0

:missing
echo.
echo [X] 缺少必要文件，已中止（未做任何破坏性操作）。
pause
exit /b 1
