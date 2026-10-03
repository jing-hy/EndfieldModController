"""「解压失败后给的路径必须**真实存在**」—— 这是本轮踩到的坑，必须钉住。

**坑的经过**（2026-10-03，用户：「**而且它显示的文件地址也显示找不到**」）：
我第一版给了 `source_path`，但对**拖入**这条路，那个文件在 `runtime\\_incoming\\`，
而 `import_mod_finish()` / `import_mod_archive()` 的 `finally` **不管成功失败都会删掉它**
⇒ 弹窗显示路径时文件早就没了 ⇒ 用户点「打开文件夹」只看到"找不到"。
第二版把包搬进 `<数据根>\\runtime\\需手动解压\\`，但对**下载**那条用的是原文件名、
对**拖入**那条用的是内部 token 名（`1791028589-39772-59503.zip`）⇒ 用户看不懂。

所以这里钉三条不变式：
  ① 失败后 `source_path` **必须真的存在**（`Path(...).is_file()` 为真）；
  ② **不能再指向 `_incoming`**（那个目录的临时文件会被 finally 清掉）；
  ③ 文件名要用**用户认识的那个**（不能是内部 token）。
"""
from __future__ import annotations

import base64
import zipfile
from pathlib import Path

from endfieldmodcontroller import api as A
from endfieldmodcontroller.config import AppConfig


def _make_broken_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("Mod/a.dds", b"D" * 20000)
    raw = bytearray(path.read_bytes())
    raw[60] ^= 0xFF                      # 弄坏文件数据区 → CRC 不过
    path.write_bytes(bytes(raw))


def _api(tmp_path: Path) -> A.EndfieldModControllerApi:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "library").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig.load(cfg_path)
    cfg.data_root = str(tmp_path)
    cfg.library_dir = "library"
    cfg.save()
    return A.EndfieldModControllerApi(str(cfg_path))


def test_failed_drop_keeps_a_real_file_with_readable_name(tmp_path: Path) -> None:
    api = _api(tmp_path)
    name = "Female Images + Dark Mode.zip"
    broken = tmp_path / name
    _make_broken_zip(broken)

    begin = api.import_mod_begin(name)
    assert begin.get("ok"), begin
    token = begin["token"]
    api.import_mod_chunk(token, base64.b64encode(broken.read_bytes()).decode())
    result = api.import_mod_finish(token)

    assert result.get("ok") is False, result
    source = Path(str(result.get("source_path") or ""))
    # ① 路径必须真实存在 —— 这是用户报的那个 bug
    assert source.is_file(), f"提示里的路径必须真实存在：{source}"
    # ② 不能再指向会被清掉的临时目录
    assert "_incoming" not in str(source)
    assert source.parent.name == "需手动解压"
    # ③ 文件名要是用户认识的那个
    assert source.name == name
    # 目标目录也要在（并且真的存在）
    assert Path(str(result["target_dir"])).is_dir()
    # 提示里要同时写出这两个路径
    assert str(source) in result["message"]
    assert result["target_dir"] in result["message"]


def test_failed_drop_name_collision_gets_suffix(tmp_path: Path) -> None:
    """同一个包连续失败两次，第二次不能覆盖第一次留下的那份。"""
    api = _api(tmp_path)
    name = "same.zip"
    for i in range(2):
        broken = tmp_path / f"src{i}.zip"
        _make_broken_zip(broken)
        begin = api.import_mod_begin(name)
        api.import_mod_chunk(begin["token"], base64.b64encode(broken.read_bytes()).decode())
        result = api.import_mod_finish(begin["token"])
        assert result.get("ok") is False

    kept = sorted((tmp_path / "runtime" / "需手动解压").iterdir())
    assert len(kept) == 2, [p.name for p in kept]
    assert all(p.is_file() for p in kept)
