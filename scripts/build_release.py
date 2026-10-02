"""构建流程的唯一入口：静态检查 → 构建最新版 → 带版本号副本 → 伪旧版 → 归置旧版 → 同步测试目录。

用法：
    python scripts/build_release.py                  # 正常构建（推荐）
    python scripts/build_release.py --skip-checks    # 跳过静态检查（只在明确知道原因时用）
    python scripts/build_release.py --skip-addon     # 不重编 ReShade 面板（沿用上次产物）
    python scripts/build_release.py --skip-modtest   # 不同步进测试目录
    python scripts/build_release.py --modtest-fake-old  # 测试目录改放伪旧版（测自更新用）

产出（全部在 `dist\\`）：

    EndfieldModController.exe                      最新版（唯一发行的 exe）
    EndfieldModController-<版本>.exe               带版本号副本（本地留档，不上传）
    EndfieldModController-0.1.9-from-<版本>.exe    伪旧版（版本号 0.1.9、代码最新，用于测自更新）
    _old\\                                         上一代及更早的带版本号副本（自动归置）

最后一步会把**一份** exe 同步进**测试目录** `..\\modtest\\`：**先清掉那里原有的 `*.exe`**，
再放最新版（带 `--modtest-fake-old` 则改放伪旧版，用来测自更新）—— 用户要求「以后都要把 modtest
里的原来的 exe 去掉，如果我没说就直接放最新版」。控制器 / 游戏 / XXMI 正在运行就**跳过、不杀进程**
（等他退出后重跑本脚本）；除 exe 外什么都不动（`config.json` / `runtime\\` / `library\\` / `assets\\`）。
`--skip-modtest` 可整步关掉。

静态检查（任一失败即中止，**不会**产出半成品）：

    1) 所有 Python 模块 py_compile
    2) 前端产物新鲜度校验（web/dist/index.html 不得比 frontend/src 旧）
    3) `python -m pytest tests -q`（必须指定 tests 目录，否则会被 `_tmp\\` 污染）

发布（上传）不在本脚本里 —— 见 `scripts/prepare_release.py`。
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_version import report as report_version_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
OLD_DIR = DIST / "_old"
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
APP_NAME = "EndfieldModController"
FAKE_VERSION = "0.1.9"
# 测试目录：默认是工作区**旁边**的 modtest（D:\zmdmod\modtest）。构建完自动把最新版 exe
# 同步进去（用户 2026-09-30：「这个需要构建脚本自动处理」—— 以前每次都要他提醒我复制）。
MODTEST_DIR = ROOT.parent / "modtest"
# 这几个进程在跑 = "控制器/游戏/XXMI 正开着"：此时**不替换 exe、也不杀进程**，等他自己退出。
GUARD_PROCESSES = ("Endfield", "XXMI Launcher", "EndfieldModController")


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK，直接 print 项目里的中文/特殊字符会崩。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_version() -> str:
    match = re.search(r'__version__ = "([^"]+)"', VERSION_PY.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("!! version.py 里找不到 __version__")
    return match.group(1)


# 发版时**必须和 version.py 一起改**的地方（用户 2026-09-30 要求：
# 「现在github的readme没更新，**以后每次推 release 的时候都要更新**」）。
README_VERSION_SOURCES: tuple[tuple[str, str], ...] = (
    ("README.md", r"当前版本\s*<b>([^<]+)</b>"),
    ("docs/README.detailed.md", r"当前版本\s*\*\*([^*]+)\*\*"),
)


def check_readme_versions(version: str) -> None:
    """卡住"改了 version.py 却忘了改 README"这件事。

    我此前连着两版（v0.7.0 / v0.7.1）都只升了 `version.py`，两份 README 停在 0.6.1，
    被用户点出来（README 是 GitHub 首页，用户一眼就能看到版本号对不对）。
    与其指望记性，不如让**构建直接失败** —— 宁可现在停下，也别把不一致的版本推上去。
    """
    problems: list[str] = []
    for relative, pattern in README_VERSION_SOURCES:
        path = ROOT / relative
        if not path.is_file():
            problems.append(f"{relative}：文件不存在")
            continue
        match = re.search(pattern, path.read_text(encoding="utf-8"))
        if not match:
            problems.append(f"{relative}：找不到「当前版本 …」那一行")
        elif match.group(1).strip() != version:
            problems.append(
                f"{relative}：写的是 {match.group(1).strip()}，而 version.py 是 {version}")
    if problems:
        print("!! 版本号不一致 —— 发版前这些地方要一起改：", flush=True)
        for item in problems:
            print(f"     {item}", flush=True)
        raise SystemExit(1)
    print(f"   版本号一致：{version}（version.py + {' + '.join(r for r, _ in README_VERSION_SOURCES)}）",
          flush=True)


def run(cmd: list[str], *, label: str) -> None:
    print(f"[build] {label} …", flush=True)
    started = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"!! {label} 失败（exit {result.returncode}），已中止，未产出任何产物")
    print(f"[build] {label} 完成（{time.time() - started:.1f}s）", flush=True)


def static_checks() -> None:
    print("[1/7] 静态检查", flush=True)
    # ① Python 语法/编译
    modules = sorted((ROOT / "endfieldmodcontroller").glob("*.py"))
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", *[str(p) for p in modules]],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"!! py_compile 失败：\n{result.stderr.strip()[:2000]}")
    print(f"      py_compile ok（{len(modules)} 个模块）", flush=True)

    # ② 前端：新版走 Vite（产物 = `web/dist/index.html`，JS/CSS 全内联的单文件）——
    #    这里校验**产物存在且不比源码旧**（"改了 frontend/ 忘了 npm run build" 是最容易犯的错，
    #    否则会静默打出一个旧界面）。旧的原生前端已删除，所以产物缺失一律直接失败。
    dist_html = ROOT / "web" / "dist" / "index.html"
    frontend_src = ROOT / "frontend" / "src"
    if dist_html.is_file():
        newest = max((p.stat().st_mtime for p in frontend_src.rglob("*") if p.is_file()),
                     default=0.0)
        if newest and dist_html.stat().st_mtime < newest:
            raise SystemExit("!! web/dist/index.html 比 frontend/src 旧 —— 请先 cd frontend && npm run build")
        print(f"      前端产物 ok（web/dist/index.html {dist_html.stat().st_size:,} B）", flush=True)
    else:
        # 旧的原生前端已在 0.9.6 删除（归档在仓库外与 git 历史里），
        # 现在只有这一条路：产物必须在。没有就直接失败，别静默打出没有界面的包。
        raise SystemExit("!! 缺少 web/dist/index.html —— 先 cd frontend && npm install && npm run build")

    # ③ 单元测试（必须指定 tests 目录）
    run([sys.executable, "-m", "pytest", "tests", "-q"], label="pytest tests -q")


def archive_old_exes(version: str) -> list[str]:
    """把 dist 里**非当前版本**的带版本号副本挪到 `_old\\`；旧伪旧版直接删。

    用户 2026-10-01 的规则：历史版本在下一版构建后归到单独目录；伪旧版"上一代用完就删"。
    """
    moved: list[str] = []
    OLD_DIR.mkdir(parents=True, exist_ok=True)
    keep = {f"{APP_NAME}.exe", f"{APP_NAME}-{version}.exe",
            f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"}
    for item in sorted(DIST.glob(f"{APP_NAME}*.exe")):
        if item.name in keep:
            continue
        if f"-{FAKE_VERSION}-from-" in item.name:
            item.unlink()
            print(f"      删除上一代伪旧版：{item.name}", flush=True)
            continue
        target = OLD_DIR / item.name
        if target.exists():
            target.unlink()
        shutil.move(str(item), str(target))
        moved.append(item.name)
        print(f"      归置旧版本：{item.name} → _old\\", flush=True)
    return moved


def clean_dist_extras() -> None:
    """让 `dist\\` 只留构建产物：清掉"跑过 exe 留下的运行数据"和 onedir 残留。

    用户 2026-10-01 要求「只留构建产物」。这些都属于可再生成的运行数据：
    `config.json` / `runtime\\` / `library\\` 是 exe 在 dist 里启动时自己建的，
    `EndfieldModController\\` 是早期 `--onedir` 构建的残留目录（与 exe 同名）。
    """
    removed: list[str] = []
    onedir = DIST / APP_NAME
    if onedir.is_dir():
        shutil.rmtree(onedir, ignore_errors=True)
        removed.append(f"{APP_NAME}\\（onedir 残留）")
    for name in ("config.json", "library", "runtime"):
        target = DIST / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            removed.append(f"{name}\\")
        elif target.is_file():
            target.unlink()
            removed.append(name)
    for item in removed:
        print(f"      清理非构建产物：{item}", flush=True)
    if not removed:
        print("      dist 里没有多余东西", flush=True)


def build_fake_old(version: str) -> None:
    """临时把版本号改成 0.1.9 构建一次，产出伪旧版（版本号旧、代码最新）。"""
    original = VERSION_PY.read_text(encoding="utf-8")
    VERSION_PY.write_text(original.replace(f'__version__ = "{version}"', f'__version__ = "{FAKE_VERSION}"'),
                          encoding="utf-8", newline="\n")
    try:
        run([sys.executable, "scripts/build_exe.py", "--skip-addon"], label=f"构建伪旧版（{FAKE_VERSION}）")
    finally:
        VERSION_PY.write_text(original, encoding="utf-8", newline="\n")
        restored = read_version()
        print(f"      version.py 已还原为 {restored}", flush=True)
        if restored != version:
            raise SystemExit(f"!! version.py 还原异常：期望 {version}，实际 {restored}")

    built = DIST / f"{APP_NAME}.exe"
    name = f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"
    target = DIST / name
    shutil.move(str(built), str(target))
    shutil.copy2(target, ROOT / name)
    print(f"      伪旧版：dist\\{name} + 根目录同名副本", flush=True)


def _running_processes() -> list[str]:
    """返回正在运行的、"会挡住替换"的进程名（没有则空列表）。"""
    quoted = ",".join(f"'{name}'" for name in GUARD_PROCESSES)
    script = (
        f"Get-Process -Name {quoted} -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty ProcessName"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []          # 查不到就当没在跑：后面拷完还有 sha256 核对兜底
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def sync_to_modtest(source: Path, *, artifact: str = "latest") -> None:
    """把**一份** exe 同步进测试目录（`<工作区父目录>\\modtest`）。

    用户 2026-09-30 的两条要求：
    ① 「**这个需要构建脚本自动处理**」—— 以前每次构建完都要他提醒我复制；
    ② 「以后都要把 modtest 里的**原来的 exe 去掉**，如果我没说就直接放**最新版**，
        你这次帮我把**伪旧版**放进去」→ 所以这里**先清掉测试目录里所有 `*.exe`**，
        再放指定的那一份：`artifact="latest"` → `EndfieldModController.exe`（默认）；
        `artifact="fake-old"` → 保持伪旧版自己的文件名。

    原则：程序/游戏**在跑就跳过，绝不为了替换去杀进程**；除 `*.exe` 之外什么都不动
    （`config.json` / `runtime\\` / `library\\` / `assets\\` 一律不碰，assets 137 MB 删了要重下）。
    """
    if not MODTEST_DIR.is_dir():
        print(f"      跳过：没有测试目录 {MODTEST_DIR}", flush=True)
        return
    running = _running_processes()
    if running:
        print(f"      跳过：{', '.join(running)} 正在运行 —— 不替换、也不杀进程；"
              f"等他退出后重跑本脚本即可", flush=True)
        return

    # ① 先清掉原来的 exe（删除类动作：先打印清单，删完**回读**确认）
    stale = sorted(MODTEST_DIR.glob("*.exe"))
    if stale:
        print(f"      清掉原有 exe（{len(stale)} 个）：{', '.join(p.name for p in stale)}", flush=True)
        for path in stale:
            try:
                path.unlink()
            except OSError as exc:
                print(f"          !! 删不掉 {path.name}: {exc}", flush=True)
        left = sorted(p.name for p in MODTEST_DIR.glob("*.exe"))
        if left:
            print(f"          !! 仍有残留（可能被占用）：{', '.join(left)}", flush=True)
    else:
        print("      测试目录里原本没有 exe", flush=True)

    # ② 放指定的那一份
    target = MODTEST_DIR / (f"{APP_NAME}.exe" if artifact == "latest" else source.name)
    shutil.copy2(source, target)
    after = sha256_of(target)
    ok = after == sha256_of(source)
    stamp = time.strftime("%H:%M:%S", time.localtime(target.stat().st_mtime))
    print(f"      放入（{artifact}）：{target.name}  {target.stat().st_size:,} B  {stamp}", flush=True)
    print(f"          sha256={after[:20]}…  与 dist 核对={'一致' if ok else '!! 不一致'}", flush=True)
    remaining = sorted(p.name for p in MODTEST_DIR.glob("*.exe"))
    print(f"      现在测试目录里的 exe：{', '.join(remaining) or '(无)'}", flush=True)


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    version = read_version()
    print(f"== 构建 EndfieldModController {version} ==", flush=True)
    check_readme_versions(version)
    # 版本号规则核对（用户 2026-10-02）：**只跟"最新 Release"比** —— 本地应为「最新 Release + 1」；
    # 只推了源码没发 Release 时不动号。查不到只提示、不中止（这条是软约束）。
    report_version_rule()

    # [0] 先编译统一控制面板（ReShade addon）：它要随进 exe，构建晚于它就等于带了旧面板。
    if "--skip-addon" in args:
        print("[0/7] 已按参数跳过面板编译（--skip-addon）", flush=True)
    else:
        print("[0/7] 编译统一控制面板（ReShade addon）", flush=True)
        run([sys.executable, "scripts/build_addon.py"], label="编译 ReShade 面板")

    if "--skip-checks" not in args:
        static_checks()
    else:
        print("[1/7] 已按参数跳过静态检查", flush=True)

    print("[2/7] 归置历史产物（旧版 → dist\\_old）+ 清理非构建产物", flush=True)
    archive_old_exes(version)
    clean_dist_extras()

    print("[3/7] 构建最新版", flush=True)
    run([sys.executable, "scripts/build_exe.py", "--skip-addon"], label="构建最新版")
    latest = DIST / f"{APP_NAME}.exe"
    if not latest.is_file():
        raise SystemExit("!! 没找到 dist/EndfieldModController.exe")
    versioned = DIST / f"{APP_NAME}-{version}.exe"
    shutil.copy2(latest, versioned)

    print("[4/7] 构建伪旧版", flush=True)
    build_fake_old(version)

    print("[5/7] 把最新版放回 dist\\EndfieldModController.exe", flush=True)
    shutil.copy2(versioned, latest)

    print("[6/7] 同步测试产物到 modtest（先清掉原有的 exe）", flush=True)
    if "--skip-modtest" in args:
        print("      已按参数跳过（--skip-modtest）", flush=True)
    elif "--modtest-fake-old" in args:
        fake_old = DIST / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"
        if fake_old.is_file():
            sync_to_modtest(fake_old, artifact="fake-old")
        else:
            print(f"      !! 找不到伪旧版 {fake_old}，跳过", flush=True)
    else:
        sync_to_modtest(latest, artifact="latest")

    print("[7/7] 产物清单", flush=True)
    for item in (latest, versioned, DIST / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe",
                 ROOT / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"):
        if item.is_file():
            stamp = time.strftime("%H:%M:%S", time.localtime(item.stat().st_mtime))
            print(f"      {item}  {item.stat().st_size:,} B  {stamp}", flush=True)
            print(f"          sha256={sha256_of(item)[:20]}…", flush=True)
        else:
            print(f"      !! 缺失 {item}", flush=True)
    if OLD_DIR.is_dir():
        olds = sorted(p.name for p in OLD_DIR.glob("*.exe"))
        if olds:
            print(f"      dist\\_old 已归置：{', '.join(olds)}", flush=True)
    # 可选：把"这一版构建时的环境"留一份快照（推 main 时 `scripts/push.py` 会自动做，这里供手动）
    if "--snapshot" in args:
        print("[8/8] 快照当前状态（--snapshot）", flush=True)
        try:
            run([sys.executable, "scripts/snapshot.py", "--label", version], label="状态快照")
        except SystemExit as exc:      # 快照失败不影响产物
            print(f"      !! 快照失败（产物不受影响）：{exc}", flush=True)

    print("\n下一步：要发布就跑 `python scripts/prepare_release.py`（备齐附件并打印上传指引）。", flush=True)
    print("      推送用 `python scripts/push.py` —— 它会**先自动快照**再推 main。", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
