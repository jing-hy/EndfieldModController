# SPDX-License-Identifier: AGPL-3.0-only
"""把 EndfieldModController 打包成单个 exe（PyInstaller）。

    python scripts/build_exe.py                    # 单文件 exe（默认，完整版）
    python scripts/build_exe.py --onedir           # 目录模式：启动更快，但不是单个文件
    python scripts/build_exe.py --console          # 保留控制台（调试 --cli 用）
    python scripts/build_exe.py --skip-addon       # 沿用上次的 ReShade 面板产物，不重编
    python scripts/build_exe.py --edition lite     # 轻量版：不打包任何 ReShade 二进制

产出：

    dist/EndfieldModController.exe            完整版（默认；产物名与行为都跟以前一样）
    dist/EndfieldModController-Lite.exe       轻量版（--edition lite）

两个形态的差别（词与 endfieldmodcontroller/edition.py 的 FULL / LITE 一致）：

* **不编译**自研 ReShade 面板（scripts/build_addon.py 整步跳过）；
* **不打包** assets/addon/（面板 .addon64）—— 轻量版运行期走不到 ReShade 链路；
* 额外打一份 edition.json（{"edition": "lite"}）到**资源根**（sys._MEIPASS 根），
  edition.py 运行期读它判形态。完整版**不打**这个文件（缺席即按 full 处理）。

  完整版与轻量版**都不再**把 DLSS5 组件包（assets/dlss5/）打进 exe —— 见下面"体积裁剪"。

⚠ 两个「根目录」必须分清，改代码时别搞混（细节见 config._detect_project_root
与 app._resource_root）：

* **用户数据根 = exe 所在目录** —— config.json / runtime/ / library/ 都落在这里，
  用户看得到、能备份，不会随进程消失；
* **只读资源根 = PyInstaller 解压目录**（sys._MEIPASS）—— web/ 等被打进
  exe 的资源在这里。

之前 PROJECT_ROOT 只写了 Path(__file__).resolve().parents[1]，打包后
__file__ 指向临时解压目录，用户的配置和 Mod 库会被写进临时目录、一退出就没了。

---------------------------------------------------------------------------
体积裁剪（2026-11-28，用户：「现在感觉 exe 有点大，有点臃肿」）
---------------------------------------------------------------------------
三处，**全部在构建期做**（不是运行期 import 失败再兜底）：

1. **角色头像不随包**（原来约 2.9 MB）—— 用户：「角色立绘可以下载后从官方拉取」。
   随包 characters.json 里本来就存着官网直链（avatar 字段），首次进角色墙时由
   character_avatars.ensure_avatars 下到 <数据根>/runtime/cache/characters/。
2. **DLSS5 组件包不随包**（assets/dlss5/*.xz，约 1.6 MB）—— 与 assets/nvngx 一样
   整组只随 assets-bundle.zip 分发，由 runtime_assets.fetch_bundle 首次启动时拉取。
   完整版原先塞进 exe 就是为了"换 exe 也能拿到新清单"，现在整组走资产包 ⇒ 没有
   那份陈旧清单挡路的问题（数据根/资产包里的清单与 exe 同批发布）。
3. **用不到的 Python 负载**（约 6.5 MB）—— 见 EXCLUDED_MODULE_PREFIXES /
   BIN_SKIP_PREFIXES / DATA_SKIP_SUFFIXES 的逐条出处。大头是 PIL._avif（4.3 MB）
   与 --collect-all webview 顺带探测进来的 twisted/setuptools 等。

⚠ 裁剪规则改完请用 scripts/build_exe.py 真打一次比对体积；**不要**为了变小去砍
校验、错误处理或用户要的功能（见 AGENTS.md「最小完整改动」）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def _fix_console() -> None:
    """把 stdout/stderr 切成 UTF-8 —— 否则**非中文 Windows** 上 print 中文会直接崩。

    实测（2026-10-10，GitHub Actions 的 windows-latest）：那里的 stdout 是 **cp1252**，
    print("打包命令：…") 抛 UnicodeEncodeError ⇒ **PyInstaller 还没开始跑就被打断**，
    整条 CI 变红（与 scripts/test_addon_hook.py 是同一个坑）。
    （CI 里已额外设 PYTHONIOENCODING=utf-8 兜底；这里补上是为了本地手动跑也稳。）
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


_fix_console()

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "exe_entry.py"
APP_NAME = "EndfieldModController"
APP_NAME_LITE = "EndfieldModController-Lite"
#: 版本形态 → exe 名（词与 endfieldmodcontroller/edition.py 的 FULL / LITE 一致）。
EDITIONS: tuple[str, ...] = ("full", "lite")
APP_NAMES: dict[str, str] = {"full": APP_NAME, "lite": APP_NAME_LITE}
#: 轻量版**一个都不打**的资产目录（ADD_DATA 里 src 以这些前缀开头的条目）。
#: assets/dlss5/ 曾经也在这里，现在**两个形态都不打**（改走 assets-bundle.zip）。
LITE_EXCLUDED_ASSET_PREFIXES: tuple[str, ...] = ("assets/addon/",)

# 只读资源：web 前端整目录 + 角色名表（含拼音别名）+ 热键词表 + 自研 ReShade 面板。
# ⚠ 这些 .json / .addon64 都是数据文件，PyInstaller 只自动收 .py —— 少一个，发布版就会
# 悄悄退化成"内置兜底数据"（角色表踩过一次：exe 里没有 characters.json，33 位角色全没了）。
# 面板也一样：没有它，「整合 Mod 快捷键」会因为"面板不存在"而拒绝锁键（这是对的，
# 但用户会以为是开关坏了），所以它必须进包。
# 前端：有 Vite 产物（web/dist/index.html）就整目录带上，否则回退原生 web/。
# ⚠️ 判据与 app.py:_index_html() 必须一致（不要用额外的标记文件 —— vite build 的
# emptyOutDir 会把它清掉）。
_WEB_SRC = "web/dist" if (ROOT / "web" / "dist" / "index.html").is_file() else "web"
ADD_DATA = [
    (_WEB_SRC, "web"),
    # 角色**名表**随包（离线也认得出角色），但**头像不随包**（2026-11-28）：
    # 表里的 avatar 直链就是下载源，图落到 <数据根>/runtime/cache/characters/。
    ("endfieldmodcontroller/characters.json", "endfieldmodcontroller"),
    ("endfieldmodcontroller/hotkey_hints.json", "endfieldmodcontroller"),
    # ⚠️ **随包组件版本表**（2026-10-03 用户要求）：给"一键启动前的更新检查"用，
    # 读它是纯本地操作（微秒级），不像以前那样同步联网查 GitHub（实测 6.1 秒）。
    ("endfieldmodcontroller/component_versions.json", "endfieldmodcontroller"),
    ("assets/addon/endfieldmodcontroller.addon64", "assets/addon"),
]

# ---------------------------------------------------------------------------
# 构建期裁剪：哪些模块 / 二进制 / 数据**不进 exe**
# ---------------------------------------------------------------------------
# 逐条都对应 build/<app>/xref-<app>.html 里真实的依赖链，别凭印象加：
#   * PIL._avif        —— AVIF 编解码扩展，单文件 4.3 MB；项目只 from PIL import Image
#                         做封面缩略图（PNG/JPEG/WebP），用不到 AVIF。
#   * twisted          —— bottle 的 server 适配器里 try: import twisted，静态分析把整棵树
#                         （含 zope/automat/constantly/hyperlink 等，约 0.94 MB）收了进来；
#                         pywebview 在 Windows 走 edgechromium，永不走 twisted。
#   * tornado/waitress —— 同上，bottle 的可选后端探测。
#   * jinja2           —— bottle 的可选模板后端（pywebview 只有错误页会用到，且不必须）。
#   * setuptools       —— cffi._shimmed_dist_utils 的构建期 shim，运行期用不到。
#   * pefile           —— PyInstaller.utils.win32.versioninfo 的依赖（打包器自己的代码）。
#   * pydoc_data       —— pydoc 的 Python 文档全文，运行期不读。
EXCLUDED_MODULE_PREFIXES: tuple[str, ...] = (
    "PIL._avif",
    "twisted",
    "tornado",
    "waitress",
    "jinja2",
    "setuptools",
    "pefile",
    "pydoc_data",
)

#: 二进制/数据条目：路径统一成 / 后按**前缀**匹配。
#:
#: ⚠️⚠️ **不要删 webview 的 win-arm64 / win-x86 loader**（2026-11-28 踩过，测试为证）：
#:   当时为了省 0.13 MB 把这两份删了，结果 exe 一点图标就崩：
#:
#:     File "webview/platforms/edgechromium.py", line 51, in <module>
#:       os.environ['Path'] += ';' + interop_dll_path(platform)
#:     File "webview/util.py", line 517, in interop_dll_path
#:       raise FileNotFoundError(f'Cannot find win-arm64')
#:
#:   —— pywebview 在 import 阶段会**枚举** webview/lib/runtimes/<platform>/native，
#:   少一个平台目录就抛异常。--cli 冒烟测不到它（那条分支在 webview 初始化之前就返回），
#:   只有真正拉起 GUI 才会暴露。test_exe_trim.py 里有一条断言钉住"这两份必须留着"。
BIN_SKIP_PREFIXES: tuple[str, ...] = (
    "PIL/_avif",
)

#: 同上，按**后缀**匹配的条目。
#:   * Python.Runtime.xml —— .NET 的 XML 注释文档（28 KB），运行期不读。
DATA_SKIP_SUFFIXES: tuple[str, ...] = (
    "pythonnet/runtime/Python.Runtime.xml",
)

HIDDEN_IMPORTS: tuple[str, ...] = (
    "clr",
    "pythonnet",
    "PIL",
    "cryptography",
    "webview.platforms.edgechromium",
)
BASE_EXCLUDES: tuple[str, ...] = (
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
)

# 应用图标（多尺寸 ico，含 16/24/32/48/64/128/256）。放进 exe 后，
# 资源管理器、任务栏、窗口标题栏都会用它。
ICON = ROOT / "assets" / "app.ico"

#: 由 build_exe.py 按上面的规则**生成**的 spec 模板（不要手改；每次构建重写）。
#: 用 __PLACEHOLDER__ 而不是 f-string：模板里全是花括号，f-string 会打架。
SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
# 由 scripts/build_exe.py 生成 —— **不要手改**，每次构建都会按当前裁剪规则重写。

NAME = __NAME__
CONSOLE = __CONSOLE__
ICON = __ICON__
UAC_ADMIN = __UAC_ADMIN__
ONEFILE = __ONEFILE__
ENTRY = __ENTRY__
DATAS = __DATAS__
HIDDEN = __HIDDEN__
EXCLUDES = __EXCLUDES__
PURE_SKIP = __PURE_SKIP__
BIN_SKIP = __BIN_SKIP__
DATA_SKIP = __DATA_SKIP__

from PyInstaller.utils.hooks import collect_all


def _norm(path):
    # chr(92) = 反斜杠：写在这里是为了不用在模板里搞多层转义
    return str(path).replace(chr(92), "/")


def _skipped(name, prefixes, suffixes=()):
    norm = _norm(name)
    if any(norm.startswith(prefix) for prefix in prefixes):
        return True
    return any(norm.endswith(suffix) for suffix in suffixes)


extra = collect_all("webview")
binaries = list(extra[1])
datas = list(DATAS) + list(extra[0])
hiddenimports = list(HIDDEN) + list(extra[2])

a = Analysis(
    [ENTRY],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
a.pure = [item for item in a.pure if not _skipped(item[0], PURE_SKIP)]
a.binaries = [item for item in a.binaries if not _skipped(item[0], BIN_SKIP, DATA_SKIP)]
a.datas = [item for item in a.datas if not _skipped(item[0], BIN_SKIP, DATA_SKIP)]

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name=NAME, debug=False, bootloader_ignore_signals=False, strip=False,
        upx=True, upx_exclude=[], runtime_tmpdir=None, console=CONSOLE,
        disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
        codesign_identity=None, entitlements_file=None, uac_admin=UAC_ADMIN,
        icon=ICON,
    )
else:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name=NAME, debug=False, bootloader_ignore_signals=False, strip=False,
        upx=True, console=CONSOLE, disable_windowed_traceback=False,
        argv_emulation=False, target_arch=None, codesign_identity=None,
        entitlements_file=None, uac_admin=UAC_ADMIN, icon=ICON,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name=NAME)
'''


def parse_edition(args: list[str]) -> str:
    """取 --edition full|lite（缺省 full）；取值非法直接中止。

    本脚本一直是手工扫 argv（--onedir / --console / --skip-addon），改成 argparse
    会让已有参数的语义变味（未知参数一律忽略），所以就在同一套风格里加这一项。
    """
    edition = "full"
    for index, item in enumerate(args):
        if item == "--edition" and index + 1 < len(args):
            edition = args[index + 1]
        elif item.startswith("--edition="):
            edition = item.split("=", 1)[1]
    value = str(edition).strip().lower()
    if value not in EDITIONS:
        raise SystemExit(f"!! --edition 只能是 {'/'.join(EDITIONS)}，收到的是 {edition!r}")
    return value


def is_reshade_asset(src: str) -> bool:
    """ADD_DATA 里这一项是否属于 ReShade 链路（轻量版一个都不打）。"""
    normalized = str(src).replace("\\", "/")
    return normalized.startswith(LITE_EXCLUDED_ASSET_PREFIXES)


def add_data_for(edition: str) -> list[tuple[str, str]]:
    """某个形态要打进 exe 的数据清单（相对仓库根的 src 路径 → 包内 dest）。

    完整版原样返回 ADD_DATA；轻量版去掉 assets/addon/ 下的条目。
    """
    if edition == "full":
        return list(ADD_DATA)
    return [item for item in ADD_DATA if not is_reshade_asset(item[0])]


def app_name_for(edition: str) -> str:
    """PyInstaller 的产物名（不带扩展名）。

    完整版沿用历史名 EndfieldModController（产物 EndfieldModController.exe，与以前一致）；
    轻量版是 EndfieldModController-Lite（产物 EndfieldModController-Lite.exe）。
    """
    return APP_NAMES[edition]


def _write_edition_json(tmp_dir: Path, edition: str) -> Path:
    """在临时目录里写 edition.json，返回路径（由调用方加进 datas 的 . 下）。"""
    path = tmp_dir / "edition.json"
    path.write_text(json.dumps({"edition": edition}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def render_spec(*, app_name: str, data_items: list[tuple[str, str]],
                onefile: bool, keep_console: bool) -> str:
    """按当前裁剪规则渲染出 PyInstaller 的 spec 文本。

    为什么不用命令行参数：excludes / hidden-import 只能**加**模块，而我们要**删**
    已经由 hook 收集进来的文件（WebView2 的 arm64/x86 loader、Python.Runtime.xml），
    只有 spec 里改 a.binaries / a.datas 才做得到。
    """
    datas = [[str((ROOT / src).resolve()), dest] for src, dest in data_items]
    replacements = {
        "__NAME__": repr(app_name),
        "__CONSOLE__": repr(bool(keep_console)),
        "__ICON__": repr(str(ICON) if ICON.is_file() else None),
        "__UAC_ADMIN__": repr(os.name == "nt"),
        "__ONEFILE__": repr(bool(onefile)),
        "__ENTRY__": repr(str(ENTRY)),
        "__DATAS__": repr(datas),
        "__HIDDEN__": repr(list(HIDDEN_IMPORTS)),
        "__EXCLUDES__": repr(list(BASE_EXCLUDES)),
        "__PURE_SKIP__": repr(list(EXCLUDED_MODULE_PREFIXES)),
        "__BIN_SKIP__": repr(list(BIN_SKIP_PREFIXES)),
        "__DATA_SKIP__": repr(list(DATA_SKIP_SUFFIXES)),
    }
    text = SPEC_TEMPLATE
    for placeholder, value in replacements.items():
        if placeholder not in text:
            raise SystemExit(f"!! spec 模板缺少占位符 {placeholder}（模板被改坏了？）")
        text = text.replace(placeholder, value)
    return text


def _write_spec(spec_dir: Path, *, app_name: str, data_items: list[tuple[str, str]],
                onefile: bool, keep_console: bool) -> Path:
    """写 spec 到临时目录；文件名 = 产物名，这样 build/<产物名> 的布局与以前一致。"""
    path = spec_dir / f"{app_name}.spec"
    path.write_text(render_spec(app_name=app_name, data_items=data_items,
                                onefile=onefile, keep_console=keep_console),
                    encoding="utf-8")
    return path


def main() -> int:
    args = list(sys.argv[1:])
    onefile = "--onedir" not in args
    keep_console = "--console" in args
    edition = parse_edition(args)
    app_name = app_name_for(edition)
    data_items = add_data_for(edition)
    print(f"[edition] {edition} → dist/{app_name}.exe（随包数据 {len(data_items)} 项）", flush=True)
    print(f"[trim] 裁掉模块 {len(EXCLUDED_MODULE_PREFIXES)} 类 / 二进制前缀 "
          f"{len(BIN_SKIP_PREFIXES)} 条 / 数据后缀 {len(DATA_SKIP_SUFFIXES)} 条", flush=True)

    # 面板必须在打之前就编好 —— 缺了它 exe 里就没有统一面板。
    # （默认自动编；--skip-addon 只给"刚编过、确认没改源码"的场合用。）
    # 轻量版**不带** assets/addon/ ⇒ 压根用不到它，编译整步跳过：否则 Lite 构建会白
    # 依赖一套编面板的工具链（而它打出来的东西又不进包）。
    if edition == "lite":
        print("[edition] lite：跳过 ReShade 面板编译（assets/addon/ 不进包）", flush=True)
    elif "--skip-addon" not in args:
        addon_script = ROOT / "scripts" / "build_addon.py"
        result = subprocess.run([sys.executable, str(addon_script)], cwd=str(ROOT))
        if result.returncode != 0:
            print("\n!! ReShade 面板编译失败（可加 --skip-addon 沿用上次产物）")
            return result.returncode
    for src, _dest in data_items:
        if not (ROOT / src).exists():
            print(f"!! 缺少随包资源：{src}")
            return 1

    # 轻量版额外打一份 edition.json 到**资源根**：edition.py 运行期按它判形态。
    # 放临时目录（不污染仓库、不进 git），跑完就删。完整版**不打**它 —— 缺席时
    # edition.current() 本来就返回 full，多一个文件反而会让完整版 exe 的字节内容变了。
    if edition == "lite":
        with tempfile.TemporaryDirectory(prefix="mc-edition-json-") as tmp:
            return _run_pyinstaller(
                app_name=app_name,
                data_items=data_items + [(str(_write_edition_json(Path(tmp), edition)), ".")],
                onefile=onefile,
                keep_console=keep_console,
            )
    return _run_pyinstaller(app_name=app_name, data_items=data_items,
                            onefile=onefile, keep_console=keep_console)


def _run_pyinstaller(*, app_name: str, data_items: list[tuple[str, str]],
                     onefile: bool, keep_console: bool) -> int:
    """生成 spec 并按它打包，核对产出。"""
    with tempfile.TemporaryDirectory(prefix="mc-spec-") as spec_dir:
        spec_path = _write_spec(Path(spec_dir), app_name=app_name,
                                data_items=data_items, onefile=onefile,
                                keep_console=keep_console)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--distpath", str(ROOT / "dist"),
            "--workpath", str(ROOT / "build"),
            str(spec_path),
        ]
        print("打包命令：\n  " + " ".join(cmd) + "\n")
        result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("\n!! 打包失败")
        return result.returncode

    target = ROOT / "dist" / (f"{app_name}.exe" if onefile else app_name)
    if target.exists():
        if target.is_file():
            size = target.stat().st_size / 1024 / 1024
            print(f"\n[OK] 产出 {target}  ({size:.1f} MB)")
        else:
            print(f"\n[OK] 产出目录 {target}")
        print("提示：exe 旁边的目录就是「用户数据根」—— config.json / runtime / library 都会生在那。")
    else:
        print(f"\n!! 没找到产出：{target}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
