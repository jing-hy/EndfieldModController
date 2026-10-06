"""发版上传脚本：draft 阶段必须也能定位到 Release（2026-10-06 实测踩到）。

**现场**：v1.0.24 发版时 `upload_release_assets.py --tag v1.0.24` 打印
`!! GitHub 上找不到 tag v1.0.24 的 Release（含 draft）` ⇒ **附件没上传**，
最后是手工 `gh release upload` 补的。

**原因**：`gh release create <tag> --draft` 创建的 draft，其 `tag_name` 是
`untagged-<hash>`（tag 要到转正时才建立），而 `push.py` **只推 main、不推 tag**
⇒ 列表接口里按 tag 名永远匹配不上。

**修法**：按 tag 匹配不上时，若列表里**恰好只有一个 draft**，就认它
（发版流程一次只开一个 draft；多个 draft 时明确报错，不猜）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import urllib.error
from unittest import mock

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "upload_release_assets.py"


@pytest.fixture()
def module():
    spec = importlib.util.spec_from_file_location("upload_release_assets", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)          # type: ignore[union-attr]
    return loaded


def _run_with_list(module, releases, tag="v9.9.9"):
    """按 tag 查 404 → 列表接口返回 releases → 调用 `_release_data`。"""
    calls = {"n": 0}

    def fake_urlopen(req, timeout=30):        # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:                   # 第一次：按 tag 查 ⇒ 404
            raise urllib.error.HTTPError("url", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        payload = mock.MagicMock()
        payload.__enter__ = lambda self: self
        payload.__exit__ = lambda self, *a: False
        payload.read = lambda: json.dumps(releases).encode()
        return payload

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        return module._release_data(tag, {})


def test_finds_release_by_tag_in_list(module):
    """列表里 tag 名对得上 ⇒ 直接用它（正常路径）。"""
    data = _run_with_list(module, [
        {"id": 1, "tag_name": "v9.9.8", "draft": False},
        {"id": 2, "tag_name": "v9.9.9", "draft": False},
    ])
    assert data["id"] == 2


def test_falls_back_to_the_only_draft(module):
    """★ draft 的 tag_name 是 untagged-… ⇒ **必须靠"唯一的 draft"兜底**，否则附件传不上去。"""
    data = _run_with_list(module, [
        {"id": 7, "tag_name": "untagged-abc123", "draft": True},
        {"id": 6, "tag_name": "v9.9.8", "draft": False},
    ])
    assert data["id"] == 7, "没有兜底的话，附件没上传这种事会重演"


def test_refuses_to_guess_when_several_drafts(module):
    """有多个 draft ⇒ 明确报错，不许瞎猜。"""
    with pytest.raises(SystemExit) as exc:
        _run_with_list(module, [
            {"id": 8, "tag_name": "untagged-b", "draft": True},
            {"id": 7, "tag_name": "untagged-a", "draft": True},
        ])
    assert "draft" in str(exc.value)


def test_missing_release_still_raises(module):
    """既没有同 tag 的、也没有 draft ⇒ 照旧报错（不许静默当成成功）。"""
    with pytest.raises(SystemExit):
        _run_with_list(module, [{"id": 6, "tag_name": "v9.9.8", "draft": False}])
