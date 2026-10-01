"""Small filesystem helpers shared by the whole controller.

2026-10-01：把两件被重复实现了 N 遍的东西收成一份 ——

* `sha256_file`：项目里曾有 6 份各自实现（dependencies / fastnet / game_clean /
  runtime_assets / selfupdate / pack_nvngx）外加两处内联。重复的代价很实在：
  "想给下载统一加校验"时改不全，就会出现**能力存在但没人用**的局面。
* `write_*_atomic`：直接 `write_text` 覆盖写，写到一半被杀/断电就留下半截文件
  （配置、controller 产物、marker 都踩过），统一走"临时文件 + os.replace"。
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Callable


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    """分块计算文件 sha256；`progress(done, total)` 可选（用于界面进度）。"""
    path = Path(path)
    digest = hashlib.sha256()
    try:
        total = path.stat().st_size
    except OSError:
        total = 0
    done = 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return digest.hexdigest()


def norm_sha256(value: str) -> str:
    """把 ``sha256:xxxx`` / 大小写混杂的期望值规范成纯小写十六进制。

    前缀匹配**不区分大小写**：GitHub 目前给的是小写 `sha256:`，但别的来源
    （自建清单、手工填写）随时可能写成 `SHA256:` 或带空格。
    """
    text = str(value or "").strip()
    if text.lower().startswith("sha256:"):
        text = text[7:]
    return text.strip().lower()


def unique_sibling(path: Path) -> Path:
    """返回一个**不会覆盖已有文件**的相邻名字（备份只增不删）。"""
    path = Path(path)
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}-{os.getpid()}")


def _tmp_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.mc-tmp-{os.getpid()}")


def write_bytes_atomic(path: Path, data: bytes, *, backup: bool = False) -> Path:
    """原子写入字节；`backup=True` 时先留一份不覆盖的 .bak。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copy2(path, unique_sibling(path.with_name(path.name + ".bak")))
    tmp = _tmp_path(path)
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


def write_text_atomic(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    backup: bool = False,
) -> Path:
    """原子写入文本（同 `write_bytes_atomic`）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copy2(path, unique_sibling(path.with_name(path.name + ".bak")))
    tmp = _tmp_path(path)
    try:
        tmp.write_text(text, encoding=encoding, newline=newline)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


# ---------------------------------------------------------------------------
# 「不要动用户的 Mod 库」护栏（用户 2026-10-01 定的硬规则）
# ---------------------------------------------------------------------------
def library_conflict(library_root: Path | None, target: Path | None) -> str:
    """目标路径与 Mod 库的关系：``""`` = 安全；否则返回**危险原因**。

    用户原话：「**任何情况（除用户手动点击移出库外）都不要动用户的 mod 库（包括换位置）**」。
    危险有三种，任何一种都不许删/移：

    * 目标**就是**库本身（`library\\`）；
    * 目标**在库里面**（`library\\某个 Mod`）—— 删它就是删用户的 Mod；
    * 目标是库的**上级目录**（例如把 `runtime\\` 或数据根当成 staging 去清空）—— 会连库一起端掉。

    为什么要有它：清理 staging、收编手动 Mod、安装/重装组件这些流程都会 `rmtree`，
    而一旦用户的 `library_dir` 与 `staging_mods_dir` 相同或互相嵌套（老教程让人把 Mod
    放进 `EFMI\\Mods`，很容易配成这样），清理 staging 就等于**把库删光**
    （2026-10-01 一条外部反馈：「重装的时候还把我 mod 都删完了，还好我备份了」）。
    """
    if library_root is None or target is None:
        return ""
    try:
        lib = Path(library_root).resolve()
        tgt = Path(target).resolve()
    except OSError:
        return ""
    if lib == tgt:
        return f"目标就是 Mod 库本身（{lib}）"
    if lib in tgt.parents:
        return f"目标在 Mod 库内（{tgt}）"
    if tgt in lib.parents:
        return f"目标是 Mod 库的上级目录（{tgt} 包含了 {lib}）"
    return ""


def is_library_safe(library_root: Path | None, target: Path | None) -> bool:
    """``library_conflict(...) == ""`` 的可读写法。"""
    return not library_conflict(library_root, target)
