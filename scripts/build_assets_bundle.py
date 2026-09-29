"""把随包资产（assets/）打成 Release 附件 assets-bundle.zip。

为什么需要它：单文件 exe 装不下约 125 MB 的运行时资产（`assets/nvngx` 是 xz 分卷，
已经压过一次），所以发行时是**两个附件**：`EndfieldModController.exe` + `assets-bundle.zip`。
程序在本地找不到 `assets\\` 时会自动从 Release 下载这个包并展开
（见 `endfieldmodcontroller/runtime_assets.py` 的 `fetch_bundle` / `_extract_bundle`，
它只接受包内 `assets/...` 路径下的条目）。

用法：
    python scripts/build_assets_bundle.py
产出：
    dist/assets-bundle.zip  （以及同名 .sha256）
"""
from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    dist = ROOT / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    if not ASSETS.is_dir():
        print(f"!! 没有 assets 目录：{ASSETS}")
        return 1
    out = dist / "assets-bundle.zip"
    count = 0
    total = 0
    # 内容本身已是 xz 压缩分卷，用 STORED 不再二次压缩（省时间，体积也没收益）
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(ASSETS.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(ROOT))   # 包内形如 assets/nvngx/...
                count += 1
                total += path.stat().st_size
    digest = sha256_of(out)
    (dist / (out.name + ".sha256")).write_text(f"{digest}  {out.name}\n", encoding="utf-8")
    print(f"[OK] {out}")
    print(f"     {count} 个文件 / 原始 {total / 1048576:.1f} MB / 包体 {out.stat().st_size / 1048576:.1f} MB")
    print(f"     sha256 {digest}")
    print("发布：Release 上传 dist\\EndfieldModController.exe + dist\\assets-bundle.zip 两个附件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
