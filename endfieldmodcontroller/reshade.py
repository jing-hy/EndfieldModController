"""Download and extract the official ReShade Add-on build.

ReShade's website distributes a setup executable whose embedded zip contains
ReShade64.dll.  We download it to a temp directory, extract with 7z, and copy
only the runtime files into the caller's target directory.  Nothing is written
into the game directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path


DEFAULT_VERSION = "6.8.0"
USER_AGENT = "EndfieldModController/0.1"


class ReShadeError(RuntimeError):
    pass


def _find_7z() -> str:
    candidates = [
        shutil.which("7z"),
        shutil.which("7za"),
        shutil.which("7zr"),
        Path(__file__).resolve().parents[1] / "tools" / "7zip" / "7z.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise ReShadeError("7z.exe was not found. Install 7-Zip or put 7z.exe in tools/7zip.")


def setup_url(version: str = DEFAULT_VERSION) -> str:
    return f"https://reshade.me/downloads/ReShade_Setup_{version}_Addon.exe"


def download_reshade(target_dir: Path, version: str = DEFAULT_VERSION) -> dict:
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    seven = _find_7z()
    url = setup_url(version)

    with tempfile.TemporaryDirectory(prefix="mc-reshade-") as tmp:
        tmp_path = Path(tmp)
        setup = tmp_path / f"ReShade_Setup_{version}_Addon.exe"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as response, open(setup, "wb") as fh:
            shutil.copyfileobj(response, fh)

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()
        result = subprocess.run(
            [seven, "x", "-y", f"-o{extract_dir}", str(setup)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            raise ReShadeError(f"7z extraction failed: {result.stderr or result.stdout}")

        copied = []
        for name in ("ReShade64.dll", "ReShade64.json", "ReShade64_XR.json"):
            source = extract_dir / name
            if source.is_file():
                shutil.copy2(source, target_dir / name)
                copied.append(str(target_dir / name))
        dll = target_dir / "ReShade64.dll"
        if not dll.is_file():
            raise ReShadeError("ReShade64.dll was not found in the official setup archive")
        return {
            "version": version,
            "url": url,
            "dll": str(dll),
            "files": copied,
        }
