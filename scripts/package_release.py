"""Build a portable source release zip under dist/."""
from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# 版本号只有一处真源：endfieldmodcontroller/version.py
from endfieldmodcontroller.version import __version__ as VERSION  # noqa: E402

INCLUDE = [
    "endfieldmodcontroller",
    "web",
    "assets",
    "reshade_addon/src",
    "reshade_addon/vendor",
    "reshade_addon/CMakeLists.txt",
    "reshade_addon/build_mingw.sh",
    "reshade_addon/build_msvc.bat",
    "scripts",
    "docs",
    "tests",
    "requirements.txt",
    "dependencies.json",
    "config.example.json",
    "run.bat",
    "run.sh",
    "README.md",
    ".gitignore",
    "dist/endfieldmodcontroller.addon",
    "dist/migoto_loader.exe",
    "dist/mc_bootstrap.dll",
]

EXCLUDE_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "build",
    "cmake-build",
    ".venv",
    "runtime",
    "library",
    "_tmp",
}


def should_skip(path: Path) -> bool:
    return any(part in EXCLUDE_PARTS for part in path.parts)


def _write(zf: zipfile.ZipFile, path: Path, arc_root: Path) -> None:
    """已压缩过的资产（.xz / .xz.partN）不再二次压缩：省时间，体积也不会更小。"""
    name = path.name.lower()
    already_packed = name.endswith(".xz") or ".xz.part" in name
    zf.write(
        path,
        arc_root / path.relative_to(ROOT),
        compress_type=zipfile.ZIP_STORED if already_packed else zipfile.ZIP_DEFLATED,
    )


def add_path(zf: zipfile.ZipFile, path: Path, arc_root: Path) -> None:
    if should_skip(path):
        return
    if path.is_file():
        _write(zf, path, arc_root)
        return
    for child in sorted(path.rglob("*")):
        if should_skip(child):
            continue
        if child.is_file():
            _write(zf, child, arc_root)


def build_assets_bundle(dist: Path) -> Path | None:
    """把随包资产（assets/）压成 Release 附件。

    单文件 exe 装不下 125 MB 的运行库，所以发布时要**两个附件**：
    `EndfieldModController.exe` + `assets-bundle.zip`。程序发现本地没有 `assets\\`
    时会自动从 Release 下载这个包并展开（见 runtime_assets.fetch_bundle）。
    内容已经是 xz 压缩过的，所以这里用 STORED 不再二次压缩。
    """
    assets = ROOT / "assets"
    if not assets.is_dir():
        print("!! 没有 assets 目录，跳过资产包")
        return None
    out = dist / "assets-bundle.zip"
    count = 0
    total = 0
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in sorted(assets.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(ROOT))
                count += 1
                total += path.stat().st_size
    print(f"built: {out}  ({count} 个文件 / {total / 1048576:.1f} MB)")
    return out


def main() -> int:
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    name = f"EndfieldModController-{VERSION}-portable.zip"
    out = dist / name
    arc_root = Path(f"EndfieldModController-{VERSION}")
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in INCLUDE:
            add_path(zf, ROOT / rel, arc_root)
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (dist / (name + ".sha256")).write_text(f"{digest}  {name}\n", encoding="utf-8")
    print(f"built: {out}")
    print(f"sha256: {digest}")
    build_assets_bundle(dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
