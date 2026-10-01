"""扫库的两条加固（2026-10-01 用户要求 B）：
① **穿透"只有一个子目录的包裹层"**；② **内容相同的重复副本只标注、不自动处理**。

起因：用户在 modtest 里看到**两个** `Hide UI＆UID` —— 因为库里真的有两份顶层目录：
```
library\\Hide UI＆UID\\                    ← 导入 zip 得到的（干净结构）
library\\【辅助】隐藏UI和UID_alt加1\\        ← 整包拷进来时多包了一层
      └─ Hide UI＆UID\\
```
两份内容逐字节相同，于是出现两个同名条目、两条都能勾选、都会进 staging。

要守住的性质：
* **包裹层不再污染识别**（组名/角色不该取到 `【辅助】隐藏UI和UID_alt加1` 这种归档名）；
* **真正的分组布局 `library/<角色>/<ModA>/ + <ModB>/` 不受影响**（那有 ≥2 个子目录）；
* 内容相同的 Mod **只标注** `duplicate_of`，**绝不自动删**（去不去重由用户决定）；
* 指纹只 stat + 读小文本，不读大文件（扫库不能被几百 MB 的贴图包拖慢）。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import core

INI = """
namespace = Test
[TextureOverride_aaaa1111_body]
hash = aaaa1111
[Constants]
global persist $coat = 0
"""


def _mod(root: Path, *parts: str, ini: str = INI, extra: bytes = b"") -> Path:
    target = root.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    (target / "0.ini").write_text(ini, encoding="utf-8")
    if extra:
        (target / "cover.bitmap").write_bytes(extra)
    return target


# --------------------------------------------------------------- ① 包裹层
def test_single_wrapper_dir_is_unwrapped(tmp_path):
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _mod(library, "【辅助】隐藏UI和UID_alt加1", "Hide UI＆UID")

    mods = core.scan_library(library, staging)

    assert len(mods) == 1, [m.name for m in mods]
    assert mods[0].name == "Hide UI＆UID"
    # 外层归档名不应污染识别（组名取里层真名）
    assert "【辅助】" not in mods[0].group, mods[0].group


def test_real_group_layout_still_expands(tmp_path):
    """两个子目录 = 真的按角色分组 → 必须各自成一个 Mod。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _mod(library, "陈千语", "夏日")
    _mod(library, "陈千语", "冬装")

    mods = core.scan_library(library, staging)

    assert len(mods) == 2, [m.name for m in mods]
    assert {m.name for m in mods} == {"夏日", "冬装"}
    assert all(m.group == "陈千语" for m in mods)


# --------------------------------------------------------------- ② 重复标注
def test_duplicate_copy_is_tagged_not_deleted(tmp_path):
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    first = _mod(library, "Hide UI＆UID", extra=b"x" * 64)
    nested = _mod(library, "【辅助】隐藏UI和UID_alt加1", "Hide UI＆UID", extra=b"x" * 64)

    mods = core.scan_library(library, staging)

    assert len(mods) == 2, [m.name for m in mods]
    tagged = [m for m in mods if m.duplicate_of]
    assert len(tagged) == 1, [(m.name, m.duplicate_of) for m in mods]
    assert tagged[0].duplicate_of == "Hide UI＆UID"
    # **只标注**：文件一个都不能少
    assert first.is_dir() and nested.is_dir()
    assert (first / "0.ini").is_file() and (nested / "0.ini").is_file()
    # 前端要能拿到这个字段（to_dict 是显式列字段的）
    assert tagged[0].to_dict()["duplicate_of"] == "Hide UI＆UID"


def test_different_mods_are_not_tagged(tmp_path):
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _mod(library, "夏日", ini=INI.replace("aaaa1111", "11111111"))
    _mod(library, "冬装", ini=INI.replace("aaaa1111", "22222222"))

    mods = core.scan_library(library, staging)

    assert len(mods) == 2
    assert all(not m.duplicate_of for m in mods), [(m.name, m.duplicate_of) for m in mods]


def test_fingerprint_ignores_large_file_contents(tmp_path):
    """指纹不读大文件：只有大文件内容不同、其余一样时，两份仍会被判为同一指纹
    （这是**刻意的**取舍 —— 只用于标注"疑似重复"，不用于删除）。"""
    library = tmp_path / "library"
    staging = tmp_path / "Mods"
    _mod(library, "A", extra=b"y" * 32)
    _mod(library, "B", extra=b"y" * 32)
    big_a = tmp_path / "library" / "A" / "big.bin"
    big_b = tmp_path / "library" / "B" / "big.bin"
    big_a.write_bytes(b"1" * 4096)
    big_b.write_bytes(b"2" * 4096)     # 内容不同、大小相同

    mods = {m.name: m for m in core.scan_library(library, staging)}

    assert len(mods) == 2
    assert any(m.duplicate_of for m in mods.values()), "同大小的大文件不读内容，应仍被判为疑似重复"
    assert core.mod_fingerprint(library / "A") == core.mod_fingerprint(library / "B")
