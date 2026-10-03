"""压缩包完整性预检：在解压**之前**认出坏包，给出可读原因。

**为什么需要**（2026-10-03 用户实测）：拖入一个下载来的 zip 时报
`解压失败：Bad CRC-32 for file 'Female Images + Dark Mode/Loadingscreens/…/Endmin_HandOnCheek.dds'`。
CRC-32 是 zip 给每个文件存的校验和，解压时算出来对不上 ⇒ **文件内容在传输/写入过程中
被破坏了**（不是 Mod 的问题、也不是解压器的错）。在这种网络环境下最常见的是：
① 断点续传的偏移算错 / 服务端返回的片段不连续（无 VPN 时香蕉网只有 0.008 MB/s，最可能）；
② 磁盘写入被中断（磁盘满 / 休眠 / 杀软实时扫描掐断）；
③ 源文件本身就坏（要靠"重下一个还坏不坏"来排除）。

**原来的体验**：坏包要等**解压到一半**才炸，用户看到一个 `BadZipFile` 堆栈，
既不知道是网络问题、也不知道该重下还是该换包。

**现在**：解压前先跑一次完整性检查，坏了就明确说"**传输过程中坏了、建议重新下载**"。
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable


def verify_archive(path: Path, *, warn: Callable[[str], None] | None = None) -> dict:
    """解压前的完整性检查。

    返回 `{"ok": bool, "kind": str, "bad_entry": str, "message": str}`：
      * `ok=True`  → 可以放心解压；
      * `ok=False` → **包是坏的**，`bad_entry` 是第一个坏掉的文件名（zip 才有），
                     `message` 是可以直接给用户看的一句话。

    **只对 zip 做逐条 CRC 校验**（标准库 `ZipFile.testzip()` 会读全部内容、算 CRC）——
    这对保证"不再出现解压到一半才炸"是必要的，代价是读一遍文件（本来解压也要读）。
    7z/rar 交给外部工具，这里只做"能不能打开"的粗检（`7z t` 太慢且依赖工具存在）。
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return {"ok": False, "kind": "empty", "bad_entry": "",
                "message": "文件是空的（没下完 / 没传完）"}

    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as zf:
                bad = zf.testzip()
        except zipfile.BadZipFile as exc:
            return {"ok": False, "kind": "not_zip", "bad_entry": "",
                    "message": f"这不是一个完整的 zip（{exc}）—— 文件多半只下/传了一半"}
        except OSError as exc:
            return {"ok": False, "kind": "io", "bad_entry": "",
                    "message": f"读取压缩包失败：{exc}"}
        if bad:
            if warn:
                warn(f"完整性检查：{path.name} 里的 {bad} CRC 校验不过")
            return {
                "ok": False, "kind": "crc", "bad_entry": bad,
                "message": (
                    f"压缩包内容损坏（CRC-32 校验不过）：\n  {bad}\n\n"
                    "这是**传输或写入过程中坏掉的**，不是 Mod 本身的问题。\n"
                    "建议：**重新下载一次**（网络不稳时断点续传可能拼错片段）；\n"
                    "      如果每次都在同一个文件上坏，那就是源包本身有问题。"
                ),
            }
        return {"ok": True, "kind": "zip", "bad_entry": "", "message": ""}

    # 7z / rar：只做"文件头能不能认出来"的粗检（真正的完整性要跑 `7z t`，太重）
    try:
        head = path.open("rb").read(8)
    except OSError as exc:
        return {"ok": False, "kind": "io", "bad_entry": "", "message": f"读取失败：{exc}"}
    known = (head.startswith(b"7z\xbc\xaf\x27\x1c") or head.startswith(b"Rar!\x1a\x07"))
    if not known:
        return {"ok": False, "kind": "unknown", "bad_entry": "",
                "message": "这个文件不像是完整的 7z / rar（文件头不对）—— 多半没下完"}
    return {"ok": True, "kind": suffixes.lstrip("."), "bad_entry": "", "message": ""}
