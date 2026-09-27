"""Download the official ReShade Add-on build into runtime/reshade and update config.json."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from endfieldmodcontroller import reshade  # noqa: E402
from endfieldmodcontroller.config import AppConfig  # noqa: E402


def main() -> int:
    cfg = AppConfig.load()
    result = reshade.download_reshade(cfg.reshade_runtime_path, reshade.DEFAULT_VERSION)
    cfg.reshade_dll = result["dll"]
    cfg.save()
    print(f"ReShade {result['version']} ready: {result['dll']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
