"""「解压失败 / 格式不支持」必须给出**源文件地址 + 目标库地址**（2026-10-03）。

用户原话：「**解压失败弹窗应该给出文件地址和目标地址，让用户自行解压放进去，
下载的解压也是**」，随后又确认：「issue 反馈的应该也是类似问题，**下载或拖入
解压失败或不支持没有弹出目标库和文件原位置**，让用户手动解压」。

所以这里钉住三条不变式：
  ① 失败结果里**同时**有 `source_path` 与 `target_dir`（能拿到源文件的场合）；
  ② 给用户的 `message` 里**真的把这两个路径写出来**（不能只有"请手动解压"）；
  ③ 提示里要有一条**可照做的做法**（含 Windows 自带 tar 的命令，免得用户先去找解压软件）。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from endfieldmodcontroller.api import _manual_extract_hint


def test_hint_contains_both_paths_and_a_command(tmp_path: Path) -> None:
    archive = tmp_path / "downloads" / "Some Mod.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"x")
    library = tmp_path / "library"

    text = _manual_extract_hint("解压失败：坏掉了", archive, library)

    # ① 源文件地址
    assert str(archive) in text
    # ② 目标库地址
    assert str(library) in text
    # ③ 可照做的做法（并且用 Windows 自带 tar，不必先装 7-Zip）
    assert "tar -xf" in text
    assert "重新扫描" in text
    # 原因也要在（用户得知道为什么）
    assert "坏掉了" in text


def test_hint_handles_paths_with_spaces(tmp_path: Path) -> None:
    """路径带空格很常见（`Female Images + Dark Mode.zip` 就是），命令必须加引号。"""
    archive = tmp_path / "Female Images + Dark Mode.zip"
    archive.write_bytes(b"x")
    library = tmp_path / "my library"
    text = _manual_extract_hint("CRC 校验不过", archive, library)
    assert f'"{archive}"' in text
    assert f'"{library}"' in text


def test_broken_zip_import_reports_paths(tmp_path: Path) -> None:
    """导入一个**真的坏掉**的 zip → 返回里必须带两个路径，且消息里写出来。

    这走的是完整链路（`_import_archive_file`），不是在测 helper。
    """
    from tests.test_import_archive import ImportArchiveTests

    case = ImportArchiveTests("test_zip_slip_is_rejected")   # 只为拿到 setUp 建好的环境
    case.setUp()
    try:
        src = tmp_path / "broken.zip"
        with zipfile.ZipFile(src, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("Mod/a.dds", b"D" * 20000)
        raw = bytearray(src.read_bytes())
        raw[60] ^= 0xFF                      # 弄坏文件数据区 → CRC 不过
        broken = tmp_path / "broken2.zip"
        broken.write_bytes(bytes(raw))

        result = case.api._import_archive_file(broken, "broken2.zip")

        assert result.get("ok") is False, result
        assert result.get("source_path"), "必须给出源文件地址"
        assert result.get("target_dir"), "必须给出目标库地址"
        assert str(broken) in result["message"]
        assert result["target_dir"] in result["message"]
    finally:
        case.tearDown()
