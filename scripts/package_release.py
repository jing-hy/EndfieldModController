"""Build a portable source release zip under dist/."""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"

INCLUDE = [
    "endfieldmodcontroller",
    "web",
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


def add_path(zf: zipfile.ZipFile, path: Path, arc_root: Path) -> None:
    if should_skip(path):
        return
    if path.is_file():
        zf.write(path, arc_root / path.relative_to(ROOT))
        return
    for child in sorted(path.rglob("*")):
        if should_skip(child):
            continue
        if child.is_file():
            zf.write(child, arc_root / child.relative_to(ROOT))


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
