# SPDX-License-Identifier: AGPL-3.0-only
"""发布流程固化：备齐 Release 附件、打印上传指引（**绝不自动上传**）。

用法：
    python scripts/prepare_release.py              # 只备**完整版**（默认，行为与以前一样）
    python scripts/prepare_release.py --edition lite   # 只备**轻量版**（Lite 的发版闸/清单）
    python scripts/prepare_release.py --all-editions   # 两版都备（Lite 存在且过关才一起发）

做的事：
    1) 校验 `dist\\` 里的 exe 是"当前版本构建出来的"（用同名带版本号副本判断）——
       不是就先跑 `python scripts/build_release.py`；
    2) 发版闸：按**形态**各核对一份构建记录 —— 完整版读 `dist/build-info.json`，
       轻量版读 `dist/build-info-lite.json`（两版各写各的文件，见 `build_release.py`）。
       完整版不过 ⇒ 中止（v1.0.19 的事故：exe 自称 beta ⇒ 用户自更新无限提示）；
       轻量版不过 / 不存在 ⇒ **只警告**，把 Lite 从上传清单里摘掉，**不中止**完整版发版；
       （默认 = 完整版 + 本地能过闸的 Lite 一起备；显式 `--edition full` 才严格只备完整版）
    3) 生成/刷新 `dist/assets-bundle.zip`（+ `.sha256`）；
    4) 打印附件名称、大小、sha256，以及现成的 `gh release create` 命令 ——
       **由你自己决定何时执行**。

发布规则（用户 2026-10-01 定）：
    * Release 只上传**不带版本号的** exe（`EndfieldModController.exe`；Lite 版过关时再带
      一份 `EndfieldModController-Lite.exe`）；带版本号副本与伪旧版只留本地；
    * 这条规则**只约束 exe**，`assets-bundle.zip` 照常上传（exe 版靠它获取随包资产）；
    * 不做便携版。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_version import report as report_version_rule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION_PY = ROOT / "endfieldmodcontroller" / "version.py"
APP_NAME = "EndfieldModController"
APP_NAME_LITE = "EndfieldModController-Lite"
REPO = "jing-hy/EndfieldModController"
#: 形态 → (不带版本号的 exe 名, 构建记录文件名)。记录文件与 `build_release.build_info_path`
#: 必须**同名**：完整版沿用历史名 `build-info.json`（发版闸一直读它），轻量版另存一份。
EDITIONS: dict[str, tuple[str, str]] = {
    "full": (f"{APP_NAME}.exe", "build-info.json"),
    "lite": (f"{APP_NAME_LITE}.exe", "build-info-lite.json"),
}


def _fix_console() -> None:
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


def _release_version(version: str) -> str:
    """发 Release 用的版本号 —— **去掉 `-beta` 后缀**（用户 2026-10-04：「推 release 的都不带 beta」）。

    本地未发版时 `version.py` 写的是 `1.0.10-beta`（= 最新 Release + 1 且加 beta），
    而线上 tag / 标题一律是 `v1.0.10`。
    """
    return re.split(r"[-+]", str(version or "").strip().lstrip("vV"))[0].strip() or "0"


def parse_editions(args: list[str]) -> list[str]:
    """本次要备哪些形态：`--all-editions` 两版都备，否则按 `--edition`（缺省 full）。

    取值口径与 `build_release.py` / `build_exe.py` 一致；脚本之间刻意不互相 import
    （对方的模块级代码会跟着执行），所以这份小解析各留一份。
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


def check_embedded_version(edition: str, target: str) -> tuple[bool, str]:
    """核对某形态的 exe「自称的版本」是否等于将要发布的正式号。

    返回 `(能否放行, 一句给人看的话)`。完整版读 `dist/build-info.json`、轻量版读
    `dist/build-info-lite.json` —— **各核各的文件**，绝不会拿 A 版的记录去证明 B 版的 exe
    （记录里的 `edition` 字段对不上就直接判不通过）。
    """
    exe_name, info_name = EDITIONS[edition]
    label = "exe" if edition == "full" else "Lite exe"
    info_path = DIST / info_name
    if not info_path.is_file():
        return False, (f"缺少 dist/{info_name} —— 无法确认 {exe_name} 内嵌的是哪一版"
                       f"（先跑 scripts/build_release.py）")
    try:
        data = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"dist/{info_name} 读不出来：{exc}"
    embedded = str((data or {}).get("version") or "")
    recorded = str((data or {}).get("edition") or "").strip().lower()
    if recorded and recorded != edition:
        return False, (f"dist/{info_name} 记的是 `{recorded}` 版，而这里要核对的是 "
                       f"`{edition}` 版 —— 两版的构建记录被弄混了")
    if embedded != target:
        return False, f"{label} 内嵌版本是 `{embedded}`，而这一版要发的是 `{target}`"
    return True, f"{label} 内嵌版本 = {embedded}，与将要发布的 v{target} 一致"


def lite_in_uploads(lite_ok: bool, wanted: list[str], args: list[str]) -> bool:
    """这次要不要把 Lite 版放进上传清单（`lite_ok` = 它存在且过了发版闸）。

    默认（命令行里没写形态）就是"完整版 + **本地能过闸的 Lite 也一起备**" —— 用户要的是
    "附件清单里有 Lite，本机没有时只警告"；而显式写了 `--edition full` 就严格只备完整版，
    显式写了 `--edition lite` / `--all-editions` 则按写来的算。
    """
    explicit = ("--all-editions" in args) or any(
        item == "--edition" or item.startswith("--edition=") for item in args)
    return bool(lite_ok) and (not explicit or "lite" in wanted)


def _report_hard_failure(edition: str) -> None:
    """完整版没过发版闸时，把"为什么必须拦"讲清楚（照搬 v1.0.19 那次事故的教训）。"""
    exe_name = EDITIONS[edition][0]
    print(f"!! **发版闸拦下**：{exe_name} 不是这一版要发的正式号。", flush=True)
    print("   exe 会自称 beta ⇒ 用户装上后自更新会无限提示（v1.0.19 出过这个事故）。", flush=True)
    print("   正确顺序：① 把版本号收成正式号（去掉 -beta）→ ② build_release.py 重建"
          " → ③ 再跑本脚本。", flush=True)


def main() -> int:
    _fix_console()
    args = sys.argv[1:]
    version = read_version()
    wanted = parse_editions(args)
    print(f"== 准备 v{version} 的发布附件（{' + '.join(EDITIONS[e][0] for e in wanted)}） ==",
          flush=True)
    # 版本号规则核对（用户 2026-10-02）：本地应为「最新 Release + 1」；只推源码没发 Release 时不动号。
    report_version_rule()

    exe = DIST / f"{APP_NAME}.exe"
    versioned = DIST / f"{APP_NAME}-{version}.exe"
    lite_exe = DIST / f"{APP_NAME_LITE}.exe"
    problems: list[str] = []
    if not exe.is_file():
        problems.append(f"缺少 {exe}")
    if not versioned.is_file():
        problems.append(f"缺少 {versioned}（说明 dist 里的 exe 不是当前版本构建的）")
    if problems:
        print("!! 先完成构建：", flush=True)
        for item in problems:
            print(f"   - {item}", flush=True)
        print("\n   请先运行：python scripts/build_release.py", flush=True)
        return 1

    target = _release_version(version)

    # ⚠️ **发版闸**（2026-10-06 加）：要发出去的那个 exe 必须**自称正式号**。
    # v1.0.19 的事故：exe 是用 `1.0.19-beta` 构建的，发版后才把源码版本号收成正式号
    # ⇒ 发出去的 exe 自称 `1.0.19-beta` ⇒ 用户装上后自更新**无限提示**
    # （原话：「1.0.19 的更新它一直让我重启并更新，但是重启后还是 beta 版」）。
    # 核对面 = `dist/build-info.json`（构建时写下的内嵌版本）；Lite 版看它自己那份记录。
    ok, message = check_embedded_version("full", target)
    if not ok:
        print(f"!! **发版闸拦下**：{message}。", flush=True)
        _report_hard_failure("full")
        return 1
    print(f"[发版闸] ok：{message}", flush=True)

    # 轻量版：只有"本机有它 + 它自称正式号"才一起发；否则**只提示**，绝不卡住完整版发版。
    lite_ok = False
    if not lite_exe.is_file():
        print(f"[发版闸] 提示：本机没有 {lite_exe.name} —— 本次只发完整版"
              f"（要一起发就用 `build_release.py --all-editions` 构建）。", flush=True)
    else:
        lite_ok, lite_message = check_embedded_version("lite", target)
        if lite_ok:
            print(f"[发版闸] ok：{lite_message}", flush=True)
        else:
            print(f"[发版闸] ⚠ Lite 版没通过：{lite_message}", flush=True)
            print("         ⇒ 这一次**不要上传 Lite 版**（下面的上传命令里也不会带它）："
                  "它同样会因自称 beta 而自更新无限提示。", flush=True)
            print("         修法：版本号收成正式号后 `python scripts/build_release.py --edition lite`"
                  " 重建，再跑本脚本。", flush=True)

    if "lite" in wanted and not lite_ok:
        print("!! 你要求备轻量版，但它不存在或没过发版闸 —— 本次**只备完整版**的附件。",
              flush=True)

    print("[1/3] 生成随包资产包", flush=True)
    result = subprocess.run([sys.executable, "scripts/build_assets_bundle.py"], cwd=str(ROOT))
    if result.returncode != 0:
        print("!! 资产包生成失败", flush=True)
        return result.returncode

    bundle = DIST / "assets-bundle.zip"
    uploads: list[Path] = [exe, bundle]
    if lite_in_uploads(lite_ok, wanted, args):
        uploads.insert(1, lite_exe)
    elif lite_ok:
        print("   提示：本机有 Lite 版且过了发版闸，但本次只备完整版"
              "（要一起发就加 --all-editions）", flush=True)
    print("\n[2/3] 本次要上传的附件", flush=True)
    for item in uploads:
        if item.is_file():
            print(f"   {item.name}  {item.stat().st_size:,} B", flush=True)
            print(f"     sha256 {sha256_of(item)}", flush=True)
        else:
            print(f"   !! 缺失 {item}", flush=True)
    print("\n   不上传（仅本地留档）：", flush=True)
    for item in (versioned, DIST / f"{APP_NAME}-0.1.9-from-{version}.exe",
                 DIST / f"{APP_NAME_LITE}-{version}.exe",
                 DIST / f"{APP_NAME_LITE}-0.1.9-from-{version}.exe"):
        print(f"   {item.name}{'' if item.is_file() else '（不存在）'}", flush=True)
    if lite_exe.is_file() and not lite_ok:
        print(f"   {lite_exe.name}（存在，但发版闸没放行 —— 先别传）", flush=True)

    # ⚠️ **发 Release 不带 beta**（用户 2026-10-04）：
    # 本地未发版时是 `1.0.10-beta`，线上 tag / 标题都用 `v1.0.10`。
    tag = f"v{target}"
    if tag != f"v{version}":
        print(f"   （本地版本是 {version}，发布用 {tag} —— beta 只存在于未发版的本地/源码里）",
              flush=True)
    print("\n[3/3] 上传指引（我没有替你上传，命令供你确认后自己执行）", flush=True)
    files = " ".join(f"\"dist\\{item.name}\"" for item in uploads)
    print(f"""
   gh release create {tag} ^
     {files} ^
     --repo {REPO} ^
     --title "{tag}" ^
     --notes "（把这一版的更新说明填在这里，或用 --notes-file RELEASE_NOTES.md）"

   提醒：
     * 版本号规则 = **只跟"最新 Release"比**、本地领先它一个；只推了源码没发 Release 时**不改号**；
     * 伪旧版（0.1.9-from-{version}）与带版本号副本**不要**上传；
     * 两版一起发时，Lite 用的随包资产另跑 `python scripts/build_assets_bundle.py --edition lite`
       （产 dist/assets-bundle-lite.zip），按同样方式核 sha256 后附上；
     * 上传前建议先核对 sha256 与上面的值一致。
""", flush=True)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
