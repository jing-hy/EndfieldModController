"""压缩包完整性预检的测试（2026-10-03）。

背景：用户实测报 `解压失败：Bad CRC-32 for file 'Female Images + Dark Mode/
Loadingscreens/Endmin/MaskOn/Endmin_HandOnCheek.dds'` —— CRC-32 是 zip 给每个文件存的
校验和，对不上说明**内容在传输/写入时坏了**（不是 Mod 的问题、也不是解压器的错）。
原来的体验是"解压到一半才炸"，用户看到一句 `BadZipFile` 不知道该重下还是该换包。
现在解压前先跑一次检查，坏了就明确说"传输过程中坏了、建议重新下载"。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from endfieldmodcontroller import archive_check


def _make_zip(path: Path, entries: dict[str, bytes], compress: int = zipfile.ZIP_STORED) -> Path:
    with zipfile.ZipFile(path, "w", compress) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return path


def test_good_zip_passes(tmp_path: Path) -> None:
    good = _make_zip(tmp_path / "good.zip", {"a/b.txt": b"hello" * 100})
    verdict = archive_check.verify_archive(good)
    assert verdict["ok"] is True
    assert verdict["kind"] == "zip"


def test_crc_corruption_is_detected_with_entry_name(tmp_path: Path) -> None:
    """把**文件数据区**改一个字节 → 中央目录仍然完好，`testzip()` 应报 CRC 错。"""
    src = _make_zip(
        tmp_path / "src.zip",
        {"Female Images + Dark Mode/Loadingscreens/Endmin/MaskOn/Endmin_HandOnCheek.dds": b"D" * 50000},
    )
    data = bytearray(src.read_bytes())
    data[60] ^= 0xFF                      # 靠前的字节一定落在文件数据里
    bad = tmp_path / "bad.zip"
    bad.write_bytes(bytes(data))

    verdict = archive_check.verify_archive(bad)
    assert verdict["ok"] is False
    assert verdict["kind"] == "crc"
    # **必须报出是哪个文件坏的** —— 这正是用户拿到的那句报错里最有用的信息
    assert "Endmin_HandOnCheek.dds" in verdict["bad_entry"]
    # 给用户的话要说清"是传输问题、建议重下"，而不是只丢一个异常名
    assert "重新下载" in verdict["message"]


def test_truncated_zip_is_rejected(tmp_path: Path) -> None:
    """半截包（下到一半/传到一半）要被拦住，而不是等解压时炸。"""
    good = _make_zip(tmp_path / "good.zip", {"a/b.txt": b"x" * 5000})
    raw = good.read_bytes()
    half = tmp_path / "half.zip"
    half.write_bytes(raw[: len(raw) // 2])

    verdict = archive_check.verify_archive(half)
    assert verdict["ok"] is False
    assert verdict["kind"] in ("not_zip", "crc")


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    empty = tmp_path / "empty.zip"
    empty.write_bytes(b"")
    verdict = archive_check.verify_archive(empty)
    assert verdict["ok"] is False
    assert verdict["kind"] == "empty"


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    verdict = archive_check.verify_archive(tmp_path / "nope.zip")
    assert verdict["ok"] is False


def test_7z_header_mismatch_is_rejected(tmp_path: Path) -> None:
    """7z/rar 只做文件头粗检；头不对（多半没下完）要拦住。"""
    fake = tmp_path / "fake.7z"
    fake.write_bytes(b"this is not a 7z at all")
    verdict = archive_check.verify_archive(fake)
    assert verdict["ok"] is False
    assert verdict["kind"] == "unknown"


def test_real_7z_header_passes(tmp_path: Path) -> None:
    """真正的 7z 文件头（`7z\xbc\xaf\x27\x1c`）应通过粗检。"""
    ok = tmp_path / "real.7z"
    ok.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)
    verdict = archive_check.verify_archive(ok)
    assert verdict["ok"] is True
