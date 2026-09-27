"""把**必须随包分发**的二进制打包成可上 GitHub 的压缩资产。

为什么需要这么绕：GitHub 对单个文件有 100 MiB 硬上限（超了 push 直接被拒），
而这些文件又**没有可用的公开下载源**，只能随仓库走：

* `assets/nvngx/` —— NVIDIA DLSS 运行库。`nvngx_dlssnr.dll` 压缩后仍有 103 MB，
  超过上限，所以对压缩流做**均分切卷**（`.part1/.part2…`）。
* `assets/dlss5/` —— DLSS5 底座里**查不到公开上游**的那几个 addon：
  `renodx-endfield-enhancer.addon64`（第一人称/相机）、`trans-zh.addon64`（面板汉化）、
  `renodx-dlss5-*.addon64`（RenoDX-DLSS5 汉化版）。它们体积小，单卷即可。

首次启动时由 `endfieldmodcontroller.runtime_assets` 自动拼接解压到 `dlss5_dir`，
用户不必自己去游戏目录、NVIDIA 官网或社区网盘找文件（开箱即用）。

用法：

    python scripts/pack_nvngx_assets.py                      # 源=runtime\\dlss5
    python scripts/pack_nvngx_assets.py --from "D:\\DLSS5"    # 源=指定目录
    python scripts/pack_nvngx_assets.py --group dlss5        # 只重打 DLSS5 组件
    python scripts/pack_nvngx_assets.py --check              # 只校验现有产物
"""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_NAME = "manifest.json"
# 单卷上限：GitHub 是 100 MiB，留 10% 余量
DEFAULT_PART_MB = 90
CHUNK = 1 << 22

# 与 runtime_assets 保持一致：x86 BCJ + LZMA2 极限压缩
FILTERS = [
    {"id": lzma.FILTER_X86},
    {"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME},
]

GROUPS: dict[str, dict] = {
    "nvngx": {
        "assets_dir": ROOT / "assets" / "nvngx",
        "patterns": ("nvngx_dlss.dll", "nvngx_dlssnr.dll"),
        "origin": "NVIDIA DLSS runtime library (nvngx_dlss*.dll)",
        "notes": (
            "NVIDIA DLSS 运行库。NVIDIA 官方 SDK 只提供 nvngx_dlss.dll，"
            "nvngx_dlssnr.dll（DLSS5 光线重建模型）没有官方直链，故随包分发；"
            "为绕开 GitHub 单文件 100 MiB 上限，压缩后按需分卷；"
            "首次启动自动拼接解压到 dlss5_dir。"
        ),
    },
    "dlss5": {
        "assets_dir": ROOT / "assets" / "dlss5",
        "patterns": (
            "renodx-endfield-enhancer.addon64",
            "trans-zh.addon64",
            "renodx-dlss5*.addon64",
        ),
        "origin": "DLSS5 addon bundle (community build; no public upstream found)",
        "notes": (
            "DLSS5 底座里没有公开下载源的三个 addon：第一人称/相机插件（Endfield Enhancer）、"
            "ReShade 面板汉化、RenoDX-DLSS5 汉化版。上游仓库均未发布 release（已逐一核查），"
            "所以只能随包分发，首次启动自动展开到 dlss5_dir。"
            "其余组件（ReShade 底座、DLSS5-Feeder、iMMERSE shader、XXMI/EFMI）走在线自动安装，"
            "不在本资产内。"
        ),
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def source_candidates(from_dir: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if from_dir is not None:
        candidates.append(from_dir)
    for env in ("MC_DLSS5_DIR",):
        value = os.environ.get(env)
        if value:
            candidates.append(Path(value))
    candidates.append(ROOT / "runtime" / "dlss5")
    return candidates


def resolve_sources(group: dict, from_dir: Path | None) -> dict[str, Path]:
    """{最终文件名: 源文件}；支持 glob（如 renodx-dlss5*.addon64）。"""
    found: dict[str, Path] = {}
    missing: list[str] = []
    for pattern in group["patterns"]:
        hit: Path | None = None
        for base in source_candidates(from_dir):
            if not base.is_dir():
                continue
            if "*" in pattern:
                matches = sorted(p for p in base.glob(pattern) if p.is_file())
                if matches:
                    hit = matches[0]
                    break
            else:
                candidate = base / pattern
                if candidate.is_file():
                    hit = candidate
                    break
        if hit is None:
            missing.append(pattern)
        else:
            found[hit.name] = hit
    if missing:
        raise FileNotFoundError(
            "找不到源文件: " + ", ".join(missing)
            + "（用 --from 指定它们所在目录，默认找 runtime\\dlss5 与 $MC_DLSS5_DIR）"
        )
    return found


def compress(src: Path, dst: Path) -> None:
    started = time.time()
    with open(src, "rb") as fi, lzma.open(dst, "wb", format=lzma.FORMAT_XZ, filters=FILTERS) as fo:
        while True:
            chunk = fi.read(CHUNK)
            if not chunk:
                break
            fo.write(chunk)
    print(
        f"  压缩 {src.name}: {src.stat().st_size:,} B → {dst.stat().st_size:,} B"
        f"（{dst.stat().st_size / src.stat().st_size:.3f}，{time.time() - started:.0f}s）"
    )


def split_even(path: Path, part_limit: int) -> list[Path]:
    """把压缩流均分成若干卷，每卷 <= part_limit；只有超限时才切。"""
    size = path.stat().st_size
    if size <= part_limit:
        return [path]
    parts = (size + part_limit - 1) // part_limit
    per = (size + parts - 1) // parts
    outputs: list[Path] = []
    with open(path, "rb") as fh:
        index = 1
        while True:
            chunk = fh.read(per)
            if not chunk:
                break
            out = path.with_name(f"{path.name}.part{index}")
            out.write_bytes(chunk)
            outputs.append(out)
            print(f"  切卷 {out.name}: {out.stat().st_size:,} B")
            index += 1
    path.unlink()
    return outputs


def build_group(key: str, group: dict, from_dir: Path | None, part_limit: int) -> int:
    assets_dir: Path = group["assets_dir"]
    assets_dir.mkdir(parents=True, exist_ok=True)
    sources = resolve_sources(group, from_dir)
    print(f"[{key}] → {assets_dir}")
    for old in assets_dir.glob("*.xz*"):
        old.unlink()

    files: dict[str, dict] = {}
    for name, src in sorted(sources.items()):
        print(f"  来源 {name}  ←  {src}")
        packed = assets_dir / f"{name}.xz"
        compress(src, packed)
        packed_bytes = packed.stat().st_size
        packed_sha = sha256_file(packed)
        parts = [p.name for p in split_even(packed, part_limit)]
        files[name] = {
            "size": src.stat().st_size,
            "sha256": sha256_file(src),
            "packed_bytes": packed_bytes,
            "packed_sha256": packed_sha,
            "parts": parts,
            # 注意：**不写本机路径**（清单要进公开仓库，个人目录名不该出现）
            "origin": group["origin"],
        }

    manifest = {
        "version": 1,
        "group": key,
        "notes": group["notes"],
        "compression": "xz (BCJ x86 + LZMA2 preset 9e)",
        "files": files,
    }
    (assets_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    total = sum(item["packed_bytes"] for item in files.values())
    print(f"  压缩后合计 {total:,} B ({total / 1048576:.2f} MB)，{len(files)} 个文件")
    for name, item in files.items():
        print(f"    {name}: {item['size']:,} B → {len(item['parts'])} 卷  sha256={item['sha256'][:16]}…")
    return 0


def build(keys: list[str], from_dir: Path | None, part_limit: int) -> int:
    for key in keys:
        try:
            build_group(key, GROUPS[key], from_dir, part_limit)
        except FileNotFoundError as exc:
            print(f"!! [{key}] {exc}", file=sys.stderr)
            return 1
        print()
    return 0


def check(keys: list[str]) -> int:
    limit = 100 * 1024 * 1024
    problems: list[str] = []
    for key in keys:
        assets_dir: Path = GROUPS[key]["assets_dir"]
        manifest_path = assets_dir / MANIFEST_NAME
        if not manifest_path.is_file():
            problems.append(f"[{key}] 没有 {manifest_path}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"[{key}] {assets_dir}")
        for name, item in (manifest.get("files") or {}).items():
            parts = [assets_dir / p for p in item["parts"]]
            missing = [p.name for p in parts if not p.is_file()]
            if missing:
                problems.append(f"[{key}] {name}: 缺分卷 {missing}")
                continue
            total = sum(p.stat().st_size for p in parts)
            if total != item["packed_bytes"]:
                problems.append(f"[{key}] {name}: 分卷总大小 {total} != {item['packed_bytes']}")
            for part in parts:
                if part.stat().st_size > limit:
                    problems.append(f"[{key}] {name}: 分卷 {part.name} 超过 100 MiB：{part.stat().st_size:,} B")
            local = ROOT / "runtime" / "dlss5" / name
            state = "未安装" if not local.is_file() else (
                "一致" if local.stat().st_size == item["size"] else f"大小不同({local.stat().st_size:,})"
            )
            print(f"  {name}: {len(parts)} 卷 / {total:,} B / sha256={item['sha256'][:16]}… / 本地 {state}")
    if problems:
        for problem in problems:
            print(f"!! {problem}", file=sys.stderr)
        return 1
    print("校验通过：分卷齐全、均未超过 100 MiB。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="打包必须随包分发的二进制为可上 GitHub 的压缩资产")
    parser.add_argument("--from", dest="from_dir", type=Path, default=None,
                        help="源文件所在目录（默认 runtime\\dlss5 与 $MC_DLSS5_DIR）")
    parser.add_argument("--group", default="all", choices=["all", *GROUPS.keys()],
                        help="只处理某一组（默认 all）")
    parser.add_argument("--part-mb", type=int, default=DEFAULT_PART_MB,
                        help=f"单卷上限 MiB（默认 {DEFAULT_PART_MB}）")
    parser.add_argument("--check", action="store_true", help="只校验现有产物，不重新打包")
    args = parser.parse_args()
    keys = list(GROUPS) if args.group == "all" else [args.group]
    if args.check:
        return check(keys)
    return build(keys, args.from_dir, args.part_mb * 1024 * 1024)


if __name__ == "__main__":
    raise SystemExit(main())
