# SPDX-License-Identifier: AGPL-3.0-only
"""构建流程的唯一入口：静态检查 → 构建最新版 → 带版本号副本 → 伪旧版 → 归置旧版 → 同步测试目录。

用法：
    python scripts/build_release.py                  # 正常构建（推荐）
    python scripts/build_release.py --with-tests     # 构建前顺便跑全量测试（内部走 run_tests.py）
    python scripts/build_release.py --skip-checks    # 跳过静态检查（只在明确知道原因时用）
    python scripts/build_release.py --skip-addon     # 不重编 ReShade 面板（沿用上次产物）
    python scripts/build_release.py --skip-modtest   # 不同步进测试目录
python scripts/build_release.py --no-push        # 不自动推 main（默认构建完就推）
    python scripts/build_release.py --with-fake-old      # 额外构建伪旧版（测自更新用，约 +19s）
python scripts/build_release.py --modtest-fake-old # 测试目录改放伪旧版（隐含 --with-fake-old）
python scripts/build_release.py --modtest-both     # 最新版与伪旧版**都**放进测试目录

两个版本形态（词与 `endfieldmodcontroller/edition.py` 一致；**默认只做完整版**）：

    python scripts/build_release.py --edition lite     # 只做轻量版（不打包任何 ReShade 二进制）
    python scripts/build_release.py --all-editions     # 一次产出完整版 + 轻量版

产出（全部在 `dist\\`）：

    EndfieldModController.exe                      完整版最新（默认，行为与以前一样）
    EndfieldModController-<版本>.exe               完整版带版本号副本（本地留档，不上传）
    EndfieldModController-0.1.9-from-<版本>.exe    完整版伪旧版（版本号 0.1.9、代码最新，测自更新）
    EndfieldModController-Lite.exe                 轻量版最新（`--edition lite` / `--all-editions`）
    EndfieldModController-Lite-<版本>.exe          轻量版带版本号副本（本地留档，不上传）
    EndfieldModController-Lite-0.1.9-from-<版本>.exe  轻量版伪旧版（同上，按需构建）
    _old\\                                         上一代及更早的带版本号副本（自动归置）

构建记录（`prepare_release.py` 的发版闸读它）：`dist/build-info.json` 记**完整版**、
`dist/build-info-lite.json` 记**轻量版** —— 两版各写各的文件，`--all-editions` 时不会互相
覆盖；两次构建写的是两个文件，谁都不会把对方那条记录写坏。

最后一步会把 exe 同步进**测试目录** `..\\modtest\\`：先清掉**本次要放的形态**原有的 `*.exe`，
再放最新版（带 `--modtest-fake-old` 则改放伪旧版，用来测自更新）。默认放**一份**；
`--all-editions` 时两版**各放一份**（`EndfieldModController.exe` / `EndfieldModController-Lite.exe`）。
只构建一版时**不会删掉另一版**（两版可以并排留在 modtest 里）。
**只有 EMC 自己**在运行才跳过同步、且不杀进程（2026-11-28 用户要求：不再检查游戏本体 / XXMI）；
除 exe 外什么都不动（`config.json` / `runtime\\` / `library\\` / `assets\\`）。
`--skip-modtest` 可整步关掉。

静态检查（任一失败即中止，**不会**产出半成品）：

    1) 所有 Python 模块 py_compile
    2) 前端产物新鲜度校验（web/dist/index.html 不得比 frontend/src 旧）

⚠️ **单元测试已经拆出去**（2026-10-09 用户要求：「本机不做**并行**构建和测试，你要拆两个
脚本出来」）—— 独立入口是 `scripts/run_tests.py`。默认**不跑**：构建与测试各自独立、都能
单独重跑；要在构建流程里带上就加 `--with-tests`（内部仍走那个脚本，本文件里不再另起一套
pytest 参数）。那个脚本**自己**按开始前的 CPU 占用决定并发（<30% ⇒ `-n 4`，否则单线程 ——
用户 2026-10-09 定的规则）。

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
APP_NAME_LITE = "EndfieldModController-Lite"
#: 版本形态 → exe 名（与 `build_exe.py` 的 `APP_NAMES` 同一套；脚本之间**刻意不互相 import**，
#: 见 `build_deps_bundle.py` 里 `_resolve_modtest_dir` 那句注释的做法）。
EDITIONS: tuple[str, ...] = ("full", "lite")
APP_NAMES: dict[str, str] = {"full": APP_NAME, "lite": APP_NAME_LITE}
FAKE_VERSION = "0.1.9"
# 测试目录：默认是工作区**旁边**的 modtest（`D:\zmdmod\modecontroller` → `D:\zmdmod\modtest`）。
# 构建完自动把最新版 exe 同步进去（用户 2026-09-30：「这个需要构建脚本自动处理」——
# 以前每次都要他提醒我复制）。
#
# ⚠️ 2026-10-09 加 `<工作区名>-modtest` 这条判据：用户把工作区放在 `D:\emc`，而他的测试
#    目录叫 `D:\emc-modtest`（不是 `D:\modtest`）。用户原话：「以后 D:\emc-modtest 等效于
#    那边的 modtest，我都会在这里测试，你构建完也复制一份进来」。
#    工作区名不带 `-modtest` 后缀且那个目录不存在时，退回原来的 `<父目录>\modtest`，
#    老布局（`D:\zmdmod`）不受影响。
def _resolve_modtest_dir() -> Path:
    sibling = ROOT.parent / f"{ROOT.name}-modtest"
    if sibling.is_dir():
        return sibling
    return ROOT.parent / "modtest"


MODTEST_DIR = _resolve_modtest_dir()
# 只有 **EMC 自己**在跑时才挡住替换（不杀进程、等他自己退出）。
# ⚠️ 2026-11-28 用户要求：**不要再检查游戏本体 / XXMI Launcher** —— 它们开着并不妨碍
#   把 exe 复制进测试目录（复制不碰它们正在用的文件），以前把它们算进去，结果
#   「游戏开着 ⇒ 整个跳过同步」，两版测试包放不进去。
# 前缀匹配：完整版是 EndfieldModController，轻量版是 EndfieldModController-Lite，都算。
GUARD_PROCESS_PREFIX = "EndfieldModController"


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


def parse_editions(args: list[str]) -> list[str]:
    """本次要构建哪些形态：`--all-editions` ⇒ 两版都做，否则按 `--edition`（缺省 full）。

    取值口径与 `build_exe.py` 的 `--edition` 一致（同一份 `EDITIONS`）。两个脚本**刻意不
    互相 import**：import 会把对方的模块级代码（控制台 reconfigure、路径探测）一并拉进来，
    所以这十几行各留一份 —— 同样的先例在 `build_deps_bundle._resolve_modtest_dir`。
    """
    if "--all-editions" in args:
        return list(EDITIONS)
    edition = "full"
    for index, item in enumerate(args):
        if item == "--edition" and index + 1 < len(args):
            edition = args[index + 1]
        elif item.startswith("--edition="):
            edition = item.split("=", 1)[1]
    value = str(edition).strip().lower()
    if value not in EDITIONS:
        raise SystemExit(f"!! --edition 只能是 {'/'.join(EDITIONS)}，收到的是 {edition!r}")
    return [value]


def edition_label(edition: str) -> str:
    return "轻量版" if edition == "lite" else "完整版"


def exe_name(edition: str) -> str:
    """某个形态「最新版」的 exe 名（不带目录）。"""
    return f"{APP_NAMES[edition]}.exe"


def versioned_name(edition: str, version: str) -> str:
    """某个形态「带版本号副本」的 exe 名。"""
    return f"{APP_NAMES[edition]}-{version}.exe"


def fake_old_name(edition: str, version: str) -> str:
    """某个形态「伪旧版」的 exe 名。"""
    return f"{APP_NAMES[edition]}-{FAKE_VERSION}-from-{version}.exe"


def build_info_path(edition: str) -> Path:
    """某个形态的构建记录文件路径。

    完整版沿用历史名 `dist/build-info.json`（`prepare_release.py` 的发版闸读它）；
    轻量版写 `dist/build-info-lite.json`。**两版各写各的文件**，因此 `--all-editions`
    或者"先建完整版、再单独建轻量版"都不会把对方那条记录覆盖掉。

    ⚠️ 轻量版构建**不动** `build-info.json`（否则发版闸会拿 Lite 的内嵌版本去核对完整版的
    exe）；反过来完整版也不碰 `build-info-lite.json`。
    """
    return DIST / ("build-info.json" if edition == "full" else f"build-info-{edition}.json")


def record_build_info(edition: str, version: str) -> None:
    """把某个形态"exe 内嵌的版本"写进它的构建记录（见 `build_info_path`）。

    `prepare_release.py` 的发版闸读这个文件：exe 必须**自称**本次要发布的正式号，否则用户
    装上后会自更新无限提示（v1.0.19 的事故）。`edition` 字段让发版闸分得清两版 ——
    「完整版的记录」和「轻量版的记录」绝不会落进同一个文件。
    """
    import json as _json

    exe = DIST / exe_name(edition)
    path = build_info_path(edition)
    try:
        path.write_text(_json.dumps({
            "version": version,
            "edition": edition,
            "artifact": exe.name,
            "sha256": sha256_of(exe),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"      !! {path.name} 写入失败：{exc}", flush=True)
        return
    # 只影响显示的路径写法（测试里 `DIST` 会被指到临时目录），失败不该让上面那次"写成功"
    # 被当成"写失败"报出来。
    try:
        shown: Path | str = path.relative_to(ROOT)
    except ValueError:
        shown = path
    print(f"      已记录 {shown}（{edition_label(edition)}内嵌版本 = {version}）", flush=True)


# 发版时**必须和 version.py 一起改**的地方（用户 2026-09-30 要求：
# 「现在github的readme没更新，**以后每次推 release 的时候都要更新**」）。
README_VERSION_SOURCES: tuple[tuple[str, str], ...] = (
    ("README.md", r"当前版本\s*<b>([^<]+)</b>"),
    ("docs/README.detailed.md", r"当前版本\s*\*\*([^*]+)\*\*"),
)


def _plain_version(value: str) -> str:
    """去掉前缀 v 与 `-beta` 之类的后缀，只留数字号。"""
    return re.split(r"[-+]", str(value or "").strip().lstrip("vV"))[0].strip()


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", _plain_version(value))) or (0,)


def latest_release_version() -> str:
    """本地 git tag 里最新的**正式**版本号（不带 v、不带 -beta）；取不到返回空串。

    只读本地 tag、**不联网** —— 构建不该因为查不到 GitHub 就失败（离线构建也要能跑）。
    """
    try:
        result = subprocess.run(["git", "tag", "-l", "v*"], cwd=str(ROOT),
                                capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except OSError:
        return ""
    best = ""
    for line in (result.stdout or "").splitlines():
        tag = line.strip()
        if not tag or re.search(r"[-+]", tag):
            continue                      # 预发布 tag 不算"最新 Release"
        if not best or _version_key(tag) > _version_key(best):
            best = _plain_version(tag)
    return best


def check_readme_versions(version: str) -> None:
    """卡住"改了 version.py 却忘了改 README" —— 但**未发版的 beta 号不许写进 README**。

    历史（2026-09-30 用户要求）：「以后每次推 release 的时候都要更新 README」——
    README 是 GitHub 首页，版本号写错一眼就看见；所以**发版时**三处必须一致。
    此前连着两版（v0.7.0 / v0.7.1）只升了 `version.py`、两份 README 停在 0.6.1，
    于是把这条做成"构建直接失败"的硬闸，而不是指望记性。

    2026-11-07 用户纠正：「为什么现在 github 上的 readme 会写 1.4.11-beta 是最新版，
    都没推上去为什么要改」⇒ 未发版（本地 `X-beta`）时，两份 README **停在最新 Release 的号**；
    真正发版时才把 version.py 收成正式号、README 跟着写成同一个正式号。
    """
    expected = version
    note = ""
    if re.search(r"[-+]", str(version or "")):
        latest = latest_release_version()
        if latest:
            expected = latest
            note = f"；未发版（{version}），README 停在最新 Release v{latest}"
    problems: list[str] = []
    for relative, pattern in README_VERSION_SOURCES:
        path = ROOT / relative
        if not path.is_file():
            problems.append(f"{relative}：文件不存在")
            continue
        match = re.search(pattern, path.read_text(encoding="utf-8"))
        if not match:
            problems.append(f"{relative}：找不到「当前版本 …」那一行")
        elif match.group(1).strip() != expected:
            problems.append(
                f"{relative}：写的是 {match.group(1).strip()}，应为 {expected}"
                + (f"（未发版不写 {version}）" if expected != version else ""))
    if problems:
        print("!! 版本号不一致 —— 发版前这些地方要一起改：", flush=True)
        for item in problems:
            print(f"     {item}", flush=True)
        raise SystemExit(1)
    print(f"   版本号一致：version.py = {version}，README/docs = {expected}{note}",
          flush=True)


def run(cmd: list[str], *, label: str) -> None:
    print(f"[build] {label} …", flush=True)
    started = time.time()
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit(f"!! {label} 失败（exit {result.returncode}），已中止，未产出任何产物")
    print(f"[build] {label} 完成（{time.time() - started:.1f}s）", flush=True)


def static_checks(*, with_tests: bool = False) -> None:
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

    # ③ 单元测试：**已经拆出去**（见 `scripts/run_tests.py`；本文件不再自带 pytest 参数）。
    #    默认**不跑** —— 本机不做"并行构建和测试"，两件事各自独立、都能单独重跑。
    if with_tests:
        run_tests_script()
    else:
        print("      单元测试：已跳过（单独跑 `python scripts/run_tests.py`；"
              "要在构建里带上就加 --with-tests）", flush=True)


def run_tests_script() -> None:
    """跑 `scripts/run_tests.py`（偶发失败自动重试）—— 只在 `--with-tests` 时调用。

    测试实现只有一份，就在那个脚本里（重试、失败行摘录、**按 CPU 占用决定并发**也都在那边）；
    本脚本不再自带 pytest 参数 —— 用户 2026-10-09 要求「本机不做并行构建和测试，你要拆两个
    脚本出来」，随后补充「如果开始前 cpu 占用小于 30 就用 4 并发」。
    失败即中止：不许产出半成品。
    """
    script = ROOT / "scripts" / "run_tests.py"
    if not script.is_file():
        raise SystemExit(f"!! 找不到 {script} —— 测试入口已拆出去，缺了它别带 --with-tests 构建")
    print("      调 scripts/run_tests.py（并发由它按本机 CPU 占用决定）…", flush=True)
    result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
    if result.returncode != 0:
        raise SystemExit("!! 测试未通过，已中止，未产出任何产物")


def archive_old_exes(version: str) -> list[str]:
    """把 dist 里**非当前版本**的带版本号副本挪到 `_old\\`；旧伪旧版直接删。

    用户 2026-10-01 的规则：历史版本在下一版构建后归到单独目录；伪旧版"上一代用完就删"。
    ⚠️ `keep` 一律按**全部形态**算（`for edition in EDITIONS`），不是只按本次构建的那几个：
    `--edition lite` 单建轻量版时，完整版的 `EndfieldModController.exe` /
    `…-<版本>.exe` 也是当前产物，绝不能因为"这次没建它"就被归进 `_old`。
    """
    moved: list[str] = []
    OLD_DIR.mkdir(parents=True, exist_ok=True)
    keep: set[str] = set()
    for edition in EDITIONS:
        keep |= {exe_name(edition), versioned_name(edition, version),
                 fake_old_name(edition, version)}
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
    `EndfieldModController\\`（以及 `EndfieldModController-Lite\\`）是 `--onedir` 构建的
    残留目录（与 exe 同名）。
    """
    removed: list[str] = []
    for edition in EDITIONS:
        onedir = DIST / APP_NAMES[edition]
        if not onedir.is_dir():
            continue
        shutil.rmtree(onedir, ignore_errors=True)
        removed.append(f"{APP_NAMES[edition]}\\（onedir 残留）")
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


def build_fake_old(version: str, edition: str) -> None:
    """临时把版本号改成 0.1.9 构建一次，产出该形态的伪旧版（版本号旧、代码最新）。

    伪旧版与正式版跑的是**同一套 PyInstaller**，只是 `version.py` 里的号临时改成 0.1.9，
    所以这里必须把 `--edition` 透传下去 —— 否则"轻量版伪旧版"会变成一份完整版 exe
    顶着 Lite 的名字，拿它测自更新根本测不到 Lite 的真实行为。
    """
    original = VERSION_PY.read_text(encoding="utf-8")
    VERSION_PY.write_text(original.replace(f'__version__ = "{version}"', f'__version__ = "{FAKE_VERSION}"'),
                          encoding="utf-8", newline="\n")
    try:
        run([sys.executable, "scripts/build_exe.py", "--skip-addon", "--edition", edition],
            label=f"构建{edition_label(edition)}伪旧版（{FAKE_VERSION}）")
    finally:
        VERSION_PY.write_text(original, encoding="utf-8", newline="\n")
        restored = read_version()
        print(f"      version.py 已还原为 {restored}", flush=True)
        if restored != version:
            raise SystemExit(f"!! version.py 还原异常：期望 {version}，实际 {restored}")

    built = DIST / exe_name(edition)
    name = fake_old_name(edition, version)
    target = DIST / name
    shutil.move(str(built), str(target))
    shutil.copy2(target, ROOT / name)
    print(f"      伪旧版：dist\\{name} + 根目录同名副本", flush=True)


def _running_processes() -> list[str]:
    """返回正在运行的 **EMC** 进程名（完整版 / 轻量版都算；没有则空列表）。

    ⚠️ 只查 EMC 自己（2026-11-28 用户要求）。游戏本体 / XXMI Launcher 开着**不影响**
    把 exe 复制进测试目录 —— 以前它们也算"挡路"，于是游戏一开着，两版测试包根本放不进去。
    """
    script = (
        "Get-Process -ErrorAction SilentlyContinue | "
        f"Where-Object {{ $_.ProcessName -like '{GUARD_PROCESS_PREFIX}*' }} | "
        "Select-Object -ExpandProperty ProcessName"
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


def _modtest_edition(name: str) -> str:
    """测试目录里的一个 exe 属于哪个形态（按产物名判断：轻量版带 -Lite）。"""
    return "lite" if "-lite" in str(name).lower() else "full"


def sync_to_modtest(sources: list[Path], *, artifact: str = "latest") -> None:
    """把 exe 同步进测试目录（`<工作区父目录>\\modtest`）。

    用户 2026-09-30 的两条要求：
    ① 「**这个需要构建脚本自动处理**」—— 以前每次构建完都要他提醒我复制；
    ② 「以后都要把 modtest 里的**原来的 exe 去掉**，如果我没说就直接放**最新版**，
        你这次帮我把**伪旧版**放进去」→ 所以这里先清掉**本次形态**的旧 exe，
        再放指定的那几份：`artifact="latest"` → 最新版；`artifact="fake-old"` → 伪旧版；
        `artifact="both"` → 两者各一份。

    放几个由 `sources` 决定（`--all-editions` 时是"完整版 + 轻量版"两个文件），**目标文件名
    一律沿用源文件名** —— 完整版因此仍是 `EndfieldModController.exe`（与以前一模一样），
    轻量版则是 `EndfieldModController-Lite.exe`（不会伪装成完整版）。

    原则：**只有 EMC 自己**在跑才跳过（2026-11-28 用户要求：不再检查游戏本体 / XXMI），
    且绝不为了替换去杀进程；除 `*.exe` 之外什么都不动
    （`config.json` / `runtime\\` / `library\\` / `assets\\` 一律不碰，assets 137 MB 删了要重下）。

    ⚠️ 清理只清**本次要放的形态**：只构建完整版时保留测试目录里的 Lite（反之亦然），
    这样两版可以一直并排放在 modtest 里测；两版都放时照旧清空重建。
    """
    if not sources:
        print("      !! 没有要放的 exe（调用方传了空清单），什么都没动", flush=True)
        return
    if not MODTEST_DIR.is_dir():
        print(f"      跳过：没有测试目录 {MODTEST_DIR}", flush=True)
        return
    running = _running_processes()
    if running:
        # ⚠️ 这里**故意不替换、也不杀进程**（禁止动用户正在用的东西）。但提示要说全：
        # 2026-10-04 就因为只写了"等他退出后重跑本脚本"，我看漏了这句、误判成"脚本静默失败"，
        # 让用户拿着旧版测了半小时。所以补上"不用重新构建、直接把 dist 那份拷过去"这条更省事的路。
        print(f"      ！跳过同步：{', '.join(running)} 正在运行 —— 不替换、也不杀进程", flush=True)
        dist_paths = "、".join(str(src) for src in sources)
        dest_paths = "、".join(str(MODTEST_DIR / src.name) for src in sources)
        print(f"        他关掉之后有两种做法：① 重跑本脚本；"
              f"② **不用重新构建**，直接把 {dist_paths} 复制到 {dest_paths}", flush=True)
        return

    # ① 先清掉**本次要放的形态**的旧 exe（删除类动作：先打印清单，删完**回读**确认）。
    #    另一形态（例如只构建完整版时的 Lite）保留 —— 两版可以并排留在 modtest 里。
    target_editions = {_modtest_edition(src.name) for src in sources}
    stale = sorted(p for p in MODTEST_DIR.glob("*.exe")
                   if _modtest_edition(p.name) in target_editions)
    if stale:
        print(f"      清掉原有 exe（{len(stale)} 个）：{', '.join(p.name for p in stale)}", flush=True)
        for path in stale:
            try:
                path.unlink()
            except OSError as exc:
                print(f"          !! 删不掉 {path.name}: {exc}", flush=True)
        # 只看**本次形态**的残留：另一形态是故意保留的，不能误报成"删不掉"。
        left = sorted(p.name for p in MODTEST_DIR.glob("*.exe")
                      if _modtest_edition(p.name) in target_editions)
        if left:
            print(f"          !! 仍有残留（可能被占用）：{', '.join(left)}", flush=True)
    else:
        print("      测试目录里没有本形态的旧 exe", flush=True)

    # ② 放置。调用方已经把"这次要放哪几份"算好了（`--modtest-both` 时最新版与伪旧版都在
    # 那份清单里；用户 2026-10-03：「这次构建最新版和伪旧版都放进 modtest」—— 两份都在，
    # 方便直接测自更新：跑伪旧版 → 它自己更新成最新版）。
    pieces: list[tuple[str, Path, Path]] = []
    for src in sources:
        if not src.is_file():
            print(f"      !! 要放的 {src.name} 其实不在 dist 里，已跳过", flush=True)
            continue
        kind = artifact
        if artifact == "both":
            kind = "fake-old" if f"-{FAKE_VERSION}-from-" in src.name else "latest"
        pieces.append((kind, src, MODTEST_DIR / src.name))
    if not pieces:
        print("      !! 清单里的 exe 一个都不在 dist 里，什么都没放", flush=True)
        return

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
    同一次 --strict 还会核对**离线依赖包**（表 vs `dist/deps-bundle.zip` 里的 manifest）：
    包是旧版同样中止（重打命令见脚本输出）。确实要带着过期表/旧离线包发版，
    用 `--skip-version-table-check` 显式跳过。
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
        print("[组件版本表] ⚠ 有组件对不上 —— 常见两种原因，按上面那段提示处理："
              "① 表过期 → 更新 `endfieldmodcontroller/component_versions.json`；"
              "② 离线包过期 → 跑 `python scripts\\build_deps_bundle.py --all-editions` 重打，再重跑本脚本；"
              "确实要跳过就加 `--skip-version-table-check`。**本轮构建已中止**。", flush=True)
        return False
    return True


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    version = read_version()
    editions = parse_editions(args)
    print(f"== 构建 EndfieldModController {version}（{' + '.join(edition_label(e) for e in editions)}） ==",
          flush=True)
    # 先把产物名打出来：两版同时构建时，一眼就能看到这次到底会产出哪几个文件
    for edition in editions:
        print(f"   {edition_label(edition)}：dist\\{exe_name(edition)}"
              f"（带版本号副本 {versioned_name(edition, version)}）", flush=True)
    check_readme_versions(version)
    # 版本号规则核对（用户 2026-10-02）：**只跟"最新 Release"比** —— 本地应为「最新 Release + 1」；
    # 只推了源码没发 Release 时不动号。查不到只提示、不中止（这条是软约束）。
    report_version_rule()
    # 随包组件版本表核对（用户 2026-10-04：「每次 release 要检查内置的依赖版本表是否最新」）：
    # 联网比一遍上游最新版，**对不上就中止构建**（--skip-version-table-check 显式跳过）。
    if not check_component_version_table(args):
        return 1

    # [0] 先编译统一控制面板（ReShade addon）：它要随进 exe，构建晚于它就等于带了旧面板。
    #     ⚠️ 只有**完整版**用得上它（`build_exe.py --edition lite` 把 `assets/addon/` 整个
    #     排除在包外）⇒ 纯轻量版构建整步跳过，省掉一套编面板的工具链。
    if "full" not in editions:
        print("[0/7] 跳过面板编译（本次只有轻量版，assets/addon/ 不进包）", flush=True)
    elif "--skip-addon" in args:
        print("[0/7] 已按参数跳过面板编译（--skip-addon）", flush=True)
    else:
        print("[0/7] 编译统一控制面板（ReShade addon）", flush=True)
        run([sys.executable, "scripts/build_addon.py"], label="编译 ReShade 面板")

    if "--skip-checks" not in args:
        static_checks(with_tests=("--with-tests" in args))
    else:
        print("[1/7] 已按参数跳过静态检查", flush=True)

    print("[2/7] 归置历史产物（旧版 → dist\\_old）+ 清理非构建产物", flush=True)
    archive_old_exes(version)
    clean_dist_extras()

    print("[3/7] 构建最新版", flush=True)
    for edition in editions:
        # `--skip-addon` 是给 `build_exe.py` 的：面板在第 0 步已经编好（或本来就跳过），
        # 打出第二份 exe 时不必再编一遍。`--edition` 决定产物名与包内资源。
        run([sys.executable, "scripts/build_exe.py", "--skip-addon", "--edition", edition],
            label=f"构建最新版（{edition_label(edition)}）")
        latest = DIST / exe_name(edition)
        if not latest.is_file():
            raise SystemExit(f"!! 没找到 dist/{exe_name(edition)}")
        shutil.copy2(latest, DIST / versioned_name(edition, version))

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
        for edition in editions:
            build_fake_old(version, edition)
    else:
        for edition in editions:
            existing_fake = DIST / fake_old_name(edition, version)
            if existing_fake.is_file():
                print(f"[4/7] 跳过{edition_label(edition)}伪旧版"
                      f"（已有 {existing_fake.name}；要重建加 --with-fake-old）", flush=True)
            else:
                print(f"[4/7] 跳过{edition_label(edition)}伪旧版（要测自更新请加 --with-fake-old）",
                      flush=True)

    print("[5/7] 把最新版放回 dist（伪旧版构建时临时占用过同名文件）", flush=True)
    for edition in editions:
        shutil.copy2(DIST / versioned_name(edition, version), DIST / exe_name(edition))

    print("[6/7] 同步测试产物到 modtest（先清掉原有的 exe）", flush=True)
    if "--skip-modtest" in args:
        print("      已按参数跳过（--skip-modtest）", flush=True)
    else:
        # 这次要放哪几份：默认最新版；`--modtest-fake-old` 改放伪旧版；`--modtest-both`
        # 两者各一份（用户 2026-10-03：「这次构建最新版和伪旧版都放进 modtest」）。
        # `--all-editions` 时每个形态各算一份，所以清单按 editions 展开。
        if "--modtest-fake-old" in args:
            artifact = "fake-old"
            wanted = [fake_old_name(edition, version) for edition in editions]
        elif "--modtest-both" in args:
            artifact = "both"
            wanted = [name for edition in editions
                      for name in (exe_name(edition), fake_old_name(edition, version))]
        else:
            artifact = "latest"
            wanted = [exe_name(edition) for edition in editions]
        for name in wanted:
            if not (DIST / name).is_file():
                hint = "（要先加 --with-fake-old 构建）" if FAKE_VERSION in name else ""
                print(f"      !! 找不到 {DIST / name}{hint}，跳过这一份", flush=True)
        sync_to_modtest([DIST / name for name in wanted], artifact=artifact)

    # 记录**实际内嵌的版本**（2026-10-06 加）：`prepare_release.py` 靠它核对
    # "要发布的这个 exe 到底自称哪一版"。v1.0.19 出过一次事故：exe 是用 `1.0.19-beta`
    # 构建的、发版后才把源码版本号收成正式号 ⇒ 发出去的 exe 自称 beta ⇒
    # 用户装上后自更新**无限提示**（「一直让我重启并更新，重启后还是 beta 版」）。
    # 两版各写各的文件（见 `build_info_path`）：`--all-editions` 时谁都不会覆盖对方；
    # 单独建轻量版时也**不动** `build-info.json`（否则发版闸会拿 Lite 的版本去核对完整版）。
    for edition in editions:
        record_build_info(edition, version)

    print("[7/7] 产物清单", flush=True)
    products: list[Path] = []
    for edition in editions:
        products += [DIST / exe_name(edition), DIST / versioned_name(edition, version),
                     DIST / fake_old_name(edition, version), ROOT / fake_old_name(edition, version)]
    for item in products:
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

    # ★ **构建完成即推 main**（2026-10-06 用户要求：
    #   「以后构建（哪怕是测试版），流程都要固化推 main」）——
    #   原因：要**两台电脑合作**，main 必须始终等于"刚构建过的那份源码"，
    #   否则另一台机器拉下来的是旧的。`push.py` 会**先做状态快照**（快照失败就不推），
    #   所以这里直接调它是安全的；它**只推 main、不发 Release**。
    #   想跳过（例如离线构建）用 `--no-push`。
    if "--no-push" in args:
        print("\n[9/9] 已按要求跳过推 main（--no-push）", flush=True)
    else:
        print("\n[9/9] 推 main（构建完成自动推送，另一台机器据此拿到同一份源码）", flush=True)
        pushed = subprocess.run([sys.executable, "scripts/push.py"], cwd=str(ROOT))
        if pushed.returncode != 0:
            print("!! 推 main 失败 —— 本地已构建但远端可能落后，请检查后手动重跑 "
                  "`python scripts/push.py`", flush=True)
            return pushed.returncode
        print("      已推 main ✓（注意：**没有**发 Release —— 发版仍需明确指示）", flush=True)

    print("\n下一步：要发布就跑 `python scripts/prepare_release.py`（备齐附件并打印上传指引）。", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
