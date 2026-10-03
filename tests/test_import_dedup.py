"""导入去重：同一个包导入两次不该在库里躺两份。

2026-10-03 用户反馈「去重没做好，现在莱万汀那里有两个一样的」：旧逻辑只做
"重名就加 `_2`/`_3` 后缀"，从不比对内容，于是同一个包连导几次就有几份
（实测那两份 **82 个文件 sha256 完全相同**）。现在解压完先比目录指纹。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller.api import _tree_digest


def _make(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


TREE = {"a.ini": "hash = 1", "sub/b.ini": "hash = 2", "sub/deep/c.txt": "x"}


def test_same_content_same_digest(tmp_path):
    a = _make(tmp_path / "one", TREE)
    b = _make(tmp_path / "two", TREE)
    assert _tree_digest(a) == _tree_digest(b)


def test_different_content_differs(tmp_path):
    a = _make(tmp_path / "one", TREE)
    b = _make(tmp_path / "two", {**TREE, "a.ini": "hash = 999"})
    assert _tree_digest(a) != _tree_digest(b)


def test_extra_file_differs(tmp_path):
    a = _make(tmp_path / "one", TREE)
    b = _make(tmp_path / "two", {**TREE, "extra.ini": "y"})
    assert _tree_digest(a) != _tree_digest(b)


def test_rename_differs(tmp_path):
    """同名同内容但**路径不同**也要算不同（Mod 目录结构本身就是信息）。"""
    a = _make(tmp_path / "one", {"a.ini": "x"})
    b = _make(tmp_path / "two", {"b.ini": "x"})
    assert _tree_digest(a) != _tree_digest(b)


def test_empty_dirs_stable(tmp_path):
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir(); b.mkdir()
    (a / "empty").mkdir(); (b / "empty2").mkdir()
    assert _tree_digest(a) == _tree_digest(b)
