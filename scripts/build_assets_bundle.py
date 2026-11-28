# SPDX-License-Identifier: AGPL-3.0-only
"""把随包资产（assets/）打成 Release 附件 assets-bundle.zip。

为什么需要它：单文件 exe 装不下约 125 MB 的运行时资产（`assets/nvngx` 是 xz 分卷，
已经压过一次），所以发行时是**两个附件**：`EndfieldModController.exe` + `assets-bundle.zip`。
程序在本地找不到 `assets\\` 时会自动从 Release 下载这个包并展开
（见 `endfieldmodcontroller/runtime_assets.py` 的 `fetch_bundle` / `_extract_bundle`，
它只接受包内 `assets/...` 路径下的条目）。

用法：
    python scripts/build_assets_bundle.py                  # 完整版（默认，行为与以前一样）
    python scripts/build_assets_bundle.py --edition lite   # 轻量版：不含任何 ReShade 资产组

产出：
    dist/assets-bundle.zip            完整版（+ 同名 `.sha256`）
    dist/assets-bundle-lite.zip       轻量版（`--edition lite`；+ 同名 `.sha256`）

轻量版**不含**的资产组（Lite 运行期走不到 ReShade 链路，带上只是白占 126 MB）：

    assets/dlss5/*    DLSS5 组件、清单、ReShade 模板与 addon 压缩包
    assets/nvngx/*    DLSS 运行库分卷（神经渲染）
    assets/addon/*    自研 ReShade 面板

其余的 `assets/rabbitfx`（EFMI 前置）等照旧保留。
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
#: 轻量版**不含**的资产组（`assets/<组>/...`）。与 `build_exe.py` 的
#: `LITE_EXCLUDED_ASSET_PREFIXES` 是同一批东西：那边决定"哪些文件进 exe"，这里决定"哪些进 zip"。
RESHADE_ASSET_GROUPS: tuple[str, ...] = ("addon", "dlss5", "nvngx")
#: 形态 → 包名（完整版沿用历史名，轻量版另起一个，两个包可以同时挂在同一个 Release 上）。
EDITIONS: tuple[str, ...] = ("full", "lite")
BUNDLE_NAMES: dict[str, str] = {"full": "assets-bundle.zip", "lite": "assets-bundle-lite.zip"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_reshade_asset(relative: Path) -> bool:
    """这个（相对仓库根的）文件是否属于 ReShade 资产组（轻量版一个都不打）。"""
    parts = relative.parts
    return len(parts) >= 2 and parts[0] == "assets" and parts[1] in RESHADE_ASSET_GROUPS


def iter_assets(edition: str) -> list[Path]:
    """要打进包的文件清单；轻量版过滤掉 ReShade 资产组，其余（含 rabbitfx）照旧。"""
    files = [path for path in sorted(ASSETS.rglob("*")) if path.is_file()]
    if edition == "full":
        return files
    return [path for path in files if not is_reshade_asset(path.relative_to(ROOT))]


def _fix_console() -> None:
    """中文 Windows 控制台默认 GBK —— `--help` 与包里那些中文路径会直接抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    _fix_console()
    parser = argparse.ArgumentParser(description="把 assets/ 打成 Release 附件")
    parser.add_argument("--edition", choices=EDITIONS, default="full",
                        help="full = 完整版（默认）；lite = 轻量版，"
                             "不含 assets/dlss5、assets/nvngx、assets/addon")
    args = parser.parse_args(argv)
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    if not ASSETS.is_dir():
        print(f"!! 没有 assets 目录：{ASSETS}")
        return 1
    out = dist / BUNDLE_NAMES[args.edition]
    count = 0
    total = 0
    # 内容本身已是 xz 压缩分卷，用 STORED 不再二次压缩（省时间，体积也没收益）
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in iter_assets(args.edition):
            archive.write(path, path.relative_to(ROOT))   # 包内形如 assets/nvngx/...
            count += 1
            total += path.stat().st_size
    digest = sha256_of(out)
    (dist / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"[OK] {out}（{args.edition} 版）")
    print(f"     {count} 个文件 / 原始 {total / 1048576:.1f} MB / 包体 {out.stat().st_size / 1048576:.1f} MB")
    print(f"     sha256 {digest}")
    if args.edition == "full":
        print("发布：Release 上传 dist\\EndfieldModController.exe + dist\\assets-bundle.zip 两个附件。")
    else:
        print("发布：dist\\EndfieldModController-Lite.exe + dist\\assets-bundle-lite.zip 两个附件"
              "（与完整版的附件放在同一个 Release 里）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
