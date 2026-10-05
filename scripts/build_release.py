"""构建流程的唯一入口：静态检查 → 构建最新版 → 带版本号副本 → 伪旧版 → 归置旧版 → 同步测试目录。

用法：
    python scripts/build_release.py                  # 正常构建（推荐）
    python scripts/build_release.py --skip-checks    # 跳过静态检查（只在明确知道原因时用）
    python scripts/build_release.py --skip-addon     # 不重编 ReShade 面板（沿用上次产物）
    python scripts/build_release.py --skip-modtest   # 不同步进测试目录
    python scripts/build_release.py --with-fake-old      # 额外构建伪旧版（测自更新用，约 +19s）
python scripts/build_release.py --modtest-fake-old # 测试目录改放伪旧版（隐含 --with-fake-old）
python scripts/build_release.py --modtest-both     # 最新版与伪旧版**都**放进测试目录

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
    frontend_dir = ROOT / "frontend"
    if dist_html.is_file():
        # ⚠️ 参与比较的输入**不只 frontend/src**（2026-10-04 修）：
        # `frontend/index.html`（主题内联脚本就在这里）、`vite.config.js`、
        # `tailwind.config.js`、`postcss.config.js`、`package.json` 改了同样会改变产物，
        # 而原判据只看 src ⇒ 改这些不重建也能通过（打出旧界面）。
        # `demo-state.json` 要排除：它会被 make_demo / normify 刷新，mtime 变新会**误伤**
        #（明明没改代码却拒绝构建）。`node_modules/` 直接跳过（几万个文件，且不是输入）。
        skip_dirs = {"node_modules", "dist", ".vite"}
        inputs: list[Path] = []
        for path in frontend_dir.iterdir():
            if path.is_file():
                if path.name != "demo-state.json":
                    inputs.append(path)
                continue
            if not path.is_dir() or path.name in skip_dirs:
                continue
            inputs.extend(p for p in path.rglob("*")
                          if p.is_file() and p.name != "demo-state.json"
                          and not skip_dirs.intersection(p.parts))
        newest = max((p.stat().st_mtime for p in inputs), default=0.0)
        if newest and dist_html.stat().st_mtime < newest:
            stale = sorted(
                (p for p in inputs if p.stat().st_mtime > dist_html.stat().st_mtime),
                key=lambda p: p.stat().st_mtime, reverse=True)[:5]
            detail = "、".join(str(p.relative_to(ROOT)) for p in stale)
            raise SystemExit(
                f"!! web/dist/index.html 比前端输入旧 —— 请先 cd frontend && npm run build\n"
                f"   比产物新的输入（前 5 个）：{detail}")
        print(f"      前端产物 ok（web/dist/index.html {dist_html.stat().st_size:,} B）", flush=True)
        # ⚠️ 产物还得**真的在 git 里**（2026-10-04）：`.gitignore` 曾用一条全局 `dist/` 把它
        # 吃掉（而同一个文件的注释却写着"要提交构建产物"），于是别人 clone 下来没有它，
        # `build_exe.py` 只能回退到 `web/` 兜底页 ⇒ 打出"界面产物缺失"的 exe。
        # 这里只**提醒**不阻断（首次入库前它本来就没被跟踪）。
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(dist_html.relative_to(ROOT))],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
            if tracked.returncode != 0:
                print("      !! web/dist/index.html 还没提交进 git —— 别人 clone 后构建会退化成"
                      "「界面产物缺失」兜底页，记得 `git add web/dist/index.html`", flush=True)
        except Exception:  # noqa: BLE001 —— 不是 git 仓库 / 没有 git 都不该阻断构建
            pass
    else:
        # 旧的原生前端已在 0.9.6 删除（归档在仓库外与 git 历史里），
        # 现在只有这一条路：产物必须在。没有就直接失败，别静默打出没有界面的包。
        raise SystemExit("!! 缺少 web/dist/index.html —— 先 cd frontend && npm install && npm run build")

    # ③ 单元测试（必须指定 tests 目录）
    run_tests()


def run_tests(attempts: int = 3) -> None:
    """跑单元测试；**偶发失败要重试**（最多 `attempts` 次）。

    为什么重试：`test_sbm_data_sync` 里会真的调 `robocopy`，在临时目录下**有概率**失败
    （2026-10-03 遇到一次：`ok: False` 但单独跑又全过）。按本项目已定的约定
    「**批量不要 fail-fast、失败项自动重试、上限 3 次**」，构建入口也不该被一次偶发卡死
    ——不过重试完仍失败就必须中止（不能靠重试掩盖真失败），并把失败的测试名列出来。
    """
    last_output = ""
    # ⚠️ **静态检查用多线程跑**（2026-10-03 提速，用户问「到底静态检查干啥了这么久，能不能多线程」）。
    # 实测：单线程 37.2s → `-n auto` **15.5s（2.4 倍）**；失败重试时省的更多
    #（最坏情况从 3×37≈111s 降到 3×15.5≈47s）。
    # 没装 `pytest-xdist` 时**优雅降级**回单线程，绝不因为缺插件而让构建失败。
    try:
        import xdist  # noqa: F401

        # ⚠️ **用固定的 4 个 worker，不用 `-n auto`**（2026-10-03 实测）：
        # `auto` 会按逻辑核数开满（本机 8 核 → 8 个），而这套测试有大量文件 IO
        #（复制/解压/扫描真实目录），worker 一多就互相拖 —— 实测同样 523 个用例，
        # `-n auto` 偶尔要 **114 秒**、`-n 4` 稳定在 **17~40 秒**，
        # 并且并行度越高越容易出现互相干扰导致的偶发失败（构建脚本因此白跑重试）。
        parallel_args = ["-n", "4"]
    except ImportError:
        parallel_args = []
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", *parallel_args],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        last_output = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            summary = [ln for ln in last_output.splitlines() if " passed" in ln]
            if attempt > 1:
                print(f"[build] pytest 第 {attempt} 次通过（前 {attempt - 1} 次是偶发失败）", flush=True)
            print(f"      {summary[-1] if summary else 'pytest ok'}", flush=True)
            return
        failed = [ln.strip() for ln in last_output.splitlines() if ln.startswith("FAILED")]
        detail = "；".join(failed[:5]) or "（没解析出 FAILED 行，见下方输出）"
        print(f"      pytest 第 {attempt}/{attempts} 次失败：{detail}", flush=True)
    raise SystemExit(
        f"!! pytest 连续 {attempts} 次失败，已中止，未产出任何产物\n{last_output[-4000:]}"
    )


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
        # ⚠️ 这里**故意不替换、也不杀进程**（禁止动用户正在用的东西）。但提示要说全：
        # 2026-10-04 就因为只写了"等他退出后重跑本脚本"，我看漏了这句、误判成"脚本静默失败"，
        # 让用户拿着旧版测了半小时。所以补上"不用重新构建、直接把 dist 那份拷过去"这条更省事的路。
        print(f"      ！跳过同步：{', '.join(running)} 正在运行 —— 不替换、也不杀进程", flush=True)
        print(f"        他关掉之后有两种做法：① 重跑本脚本；"
              f"② **不用重新构建**，直接把 {source.parent / (APP_NAME + '.exe')} 复制到 "
              f"{MODTEST_DIR / (APP_NAME + '.exe')}", flush=True)
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

    # ② 放置。`artifact="both"` 时**最新版与伪旧版各放一份**
    #（用户 2026-10-03：「这次构建最新版和伪旧版都放进 modtest」—— 两份都在，
    #  方便直接测自更新：跑伪旧版 → 它自己更新成最新版）。
    if artifact == "both":
        dist = source.parent
        candidates: list[tuple[str, Path, Path]] = []
        latest = dist / f"{APP_NAME}.exe"
        if latest.is_file():
            candidates.append(("latest", latest, MODTEST_DIR / f"{APP_NAME}.exe"))
        fake = sorted(dist.glob(f"{APP_NAME}-0.1.9-from-*.exe")) or \
            sorted(p for p in dist.glob("*.exe") if p.name != f"{APP_NAME}.exe")
        if fake:
            candidates.append(("fake-old", fake[-1], MODTEST_DIR / fake[-1].name))
        if not candidates:
            print("      !! dist 里既没有最新版也没有伪旧版，什么都没放", flush=True)
            return
        pieces = candidates
    else:
        target = MODTEST_DIR / (f"{APP_NAME}.exe" if artifact == "latest" else source.name)
        pieces = [(artifact, source, target)]

    for kind, src, target in pieces:
        shutil.copy2(src, target)
        after = sha256_of(target)
        ok = after == sha256_of(src)
        stamp = time.strftime("%H:%M:%S", time.localtime(target.stat().st_mtime))
        print(f"      放入（{kind}）：{target.name}  {target.stat().st_size:,} B  {stamp}", flush=True)
        print(f"          sha256={after[:20]}…  与 dist 核对={'一致' if ok else '!! 不一致'}", flush=True)
    remaining = sorted(p.name for p in MODTEST_DIR.glob("*.exe"))
    print(f"      现在测试目录里的 exe：{', '.join(remaining) or '(无)'}", flush=True)


def check_component_version_table(args: list[str]) -> None:
    """发版前核对「随包组件版本表」是不是上游最新（用户 2026-10-04 要求）。

    用户原话：「**另外每次 release 要检查内置的依赖版本表是否最新**」。

    为什么要查：`endfieldmodcontroller/component_versions.json` 是"随包快照"，一键启动前的
    更新提示**只读它、不联网**（用户 2026-10-03 定的，联网要干等 6.1 秒）。所以它过期就会
    误导用户 —— 提示了并不存在的新版，或漏掉真正的新版。发版是它唯一的刷新时机。

    **联网**（几秒）。有差异就**中止构建**（这是"发版前检查"的本意，用户 2026-10-04
    要的就是这个）；离线/限流查不到时不算过期、不阻断（脚本本身不误报）。
    确实要带着过期表发版，用 `--skip-version-table-check` 显式跳过。
    """
    if "--skip-version-table-check" in args:
        print("[组件版本表] 已按 --skip-version-table-check 跳过核对", flush=True)
        return True
    print("[组件版本表] 核对随包快照 vs 上游最新（联网）…", flush=True)
    try:
        result = subprocess.run(
            # ⚠️ **必须带 `--strict`**（2026-10-05 修）：脚本默认"永远 return 0"，
            #    原来这里没传 ⇒ 下面那段 `returncode != 0` 的警告**从来没打印过**，
            #    过期表就这么静默跟着 Release 发出去了（v1.0.11 就是这么漏的：
            #    Poser 0.5.18→0.5.31、乳摇 2.3.5→3.1.2 两项过期）。
            [sys.executable, "scripts/check_component_versions.py", "--strict"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[组件版本表] 检查没跑起来（忽略，不阻断构建）: {exc}", flush=True)
        return True
    for line in (result.stdout or "").strip().splitlines():
        print("  " + line, flush=True)
    if result.returncode != 0:
        print("[组件版本表] ⚠ 有组件对不上 —— 请先更新 "
              "`endfieldmodcontroller/component_versions.json` 再重跑；"
              "确实要跳过就加 `--skip-version-table-check`。**本轮构建已中止**。", flush=True)
        return False
    return True


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    version = read_version()
    print(f"== 构建 EndfieldModController {version} ==", flush=True)
    check_readme_versions(version)
    # 版本号规则核对（用户 2026-10-02）：**只跟"最新 Release"比** —— 本地应为「最新 Release + 1」；
    # 只推了源码没发 Release 时不动号。查不到只提示、不中止（这条是软约束）。
    report_version_rule()
    # 随包组件版本表核对（用户 2026-10-04：「每次 release 要检查内置的依赖版本表是否最新」）：
    # 联网比一遍上游最新版，**对不上就中止构建**（--skip-version-table-check 显式跳过）。
    if not check_component_version_table(args):
        return 1

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

    # ⚠️ **伪旧版改为按需构建**（2026-10-03 提速）：它跟"最新版"跑的是**同一套 PyInstaller**，
    # 只是把 version.py 临时改成 0.1.9 再打一次 —— 实测整整 **19.3 秒**，
    # 而绝大多数构建根本不需要它（只有要测自更新时才要）。
    # 需要时用 `--with-fake-old`（或 `--modtest-fake-old`，它隐含需要伪旧版）。
    # ⚠️ **`--modtest-both` 也必须触发伪旧版构建**（2026-10-04 修）：它的语义就是
    # "最新版 + 伪旧版**各放一份**进 modtest"（见第 6 步），而原来这里的判据漏了它 ——
    # 结果传了 `--modtest-both` 却只构建最新版，第 6 步打印一句"找不到伪旧版"就过去了，
    # **用户想测自更新时 modtest 里根本没有那个伪旧版**（表面成功、实际少做一半）。
    need_fake_old = (("--with-fake-old" in args) or ("--modtest-fake-old" in args)
                     or ("--modtest-both" in args))
    if need_fake_old:
        print("[4/7] 构建伪旧版", flush=True)
        build_fake_old(version)
    else:
        existing_fake = DIST / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"
        if existing_fake.is_file():
            print(f"[4/7] 跳过伪旧版（已有 {existing_fake.name}；要重建加 --with-fake-old）",
                  flush=True)
        else:
            print("[4/7] 跳过伪旧版（要测自更新请加 --with-fake-old）", flush=True)

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
    elif "--modtest-both" in args:
        # 最新版 + 伪旧版**各放一份**（用户 2026-10-03：「这次构建最新版和伪旧版都放进 modtest」）
        fake_old = DIST / f"{APP_NAME}-{FAKE_VERSION}-from-{version}.exe"
        if not fake_old.is_file():
            print(f"      !! 找不到伪旧版 {fake_old} —— 只放最新版", flush=True)
        sync_to_modtest(latest, artifact="both")
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
