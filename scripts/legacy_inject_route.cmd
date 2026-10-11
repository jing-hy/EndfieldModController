@REM SPDX-License-Identifier: GPL-3.0-or-later
@echo off
rem ============================================================================
rem  ModeController - LEGACY �ֶ����ߣ������ڵ�ǰ�ٷ� XXMI/EFMI ·�ߣ�
rem  [encoding: GBK/936, Windows cmd]   ������ docs\��ʷ�ɹ�·��-������ע��.md
rem
rem  ���ã����� 2026-09-27 09:31~11:28 �Ǵ�ȷ�Ͽ��õ�ע����·
rem        migoto_loader2.exe ��ѯ Endfield.exe
rem          -> ע�� mc_bootstrap.dll
rem          -> ���ڽ����ڵ� dxgi.dll ������ LoadLibrary runtime\migoto\d3d11.dll
rem          -> d3dx.ini ���� Core\EFMI\main.ini + Mods\MC_*
rem
rem  ǰ�᣺��Ϸ�����ɹٷ��������㡸DirectX 11 ��������D3D12 �²���Ч��
rem  ���ű�ֻ�������£��ָ���ͣ�ŵ�ע����/�š����� Mods������ע������
rem  ��������ϷĿ¼�������ٷ� XXMI ��װ����ԭ�������ű�ĩβ��ʾ��
rem ============================================================================
setlocal enableextensions
set "ROOT=%~dp0.."
set "MG=%ROOT%\runtime\migoto"
set "STAGE=%ROOT%\runtime\builtin\XXMI\EFMI\Mods"

if not exist "%MG%" (
  echo [X] �Ҳ��� runtime\migoto��%MG%
  pause
  exit /b 1
)

echo [1/5] ����Ƿ����йٷ� XXMI ������ ...
set "PROBE=%TEMP%\mc_legacy_probe.txt"
tasklist /FI "IMAGENAME eq XXMI Launcher.exe" > "%PROBE%" 2>nul
findstr /I /C:"XXMI Launcher.exe" "%PROBE%" >nul
if not errorlevel 1 (
  echo     [!] XXMI Launcher �������С�
  echo         ����ע����·ͬʱ���ڻ��ظ� Hook��������ʷ·��ǰ���ȹص��ٷ� XXMI/EFMI��
)
del "%PROBE%" >nul 2>&1

echo [2/5] �ָ���ͣ�ŵ�ע�������� ...
call :restore "%MG%\migoto_loader2.exe"
call :restore "%MG%\mc_bootstrap.dll"
if not exist "%MG%\migoto_loader2.exe" goto :missing
if not exist "%MG%\mc_bootstrap.dll"    goto :missing
if not exist "%MG%\d3d11.dll" (
  echo     [!] ȱ�� %MG%\d3d11.dll��EFMI �� DLL��v1.1.9��
  goto :missing
)

echo [3/5] д��ע��˳�� inject_order.txt = mc_bootstrap.dll ...
> "%MG%\inject_order.txt" echo mc_bootstrap.dll

echo [4/5] ׼�� Mods Ŀ¼���� EFMI staging ���ƣ�...
if not exist "%MG%\Mods" mkdir "%MG%\Mods"
if exist "%STAGE%" (
  robocopy "%STAGE%" "%MG%\Mods" /E /NFL /NDL /NJH /NJS >nul
  if errorlevel 8 (
    echo     [!] robocopy ���� %errorlevel%������ Mods �Ƿ���������
  ) else (
    echo     ��ͬ�� Mods��%STAGE%
  )
) else (
  echo     [!] �Ҳ��� staging Ŀ¼ %STAGE%��Mods ����ԭ����
)

echo [5/5] ����ע������������С�����ڣ������ѯ 300 �룩...
start "ModeController legacy injector" /MIN "%MG%\migoto_loader2.exe"

echo.
echo ============================================================
echo  ע�����������������룺
echo    1) �򿪹ٷ�������
echo    2) �㡸DirectX 11 ����������Ҫ����ͨ��ʼ��ť��
echo.
echo  Լ 30 �����֤��
echo    type "%MG%\mc_bootstrap.log"
echo       ������loading EFMI dll=...  Ȼ�� load result h=... err=0
echo    findstr /C:"Processing" "%MG%\d3d11_log.txt"
echo       ������Processing "...\Mods\MC_xxx\...ini"
echo    findstr /C:"Loading custom resource" "%MG%\d3d11_log.txt"
echo       ������Loading custom resource ...\Mods\MC_xxx\...dds as DDS
echo.
echo  ��ԭ���������˾�ִ�У���
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
  echo     [i] �ѻָ� %~nx1
  exit /b 0
)
echo     [!] ��û�� %~nx1��Ҳû�� %~nx1.modecontroller.disabled
exit /b 0

:missing
echo.
echo [X] ȱ�ٱ�Ҫ�ļ�������ֹ��δ���κ��ƻ��Բ�������
pause
exit /b 1
