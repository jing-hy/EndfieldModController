"""钉住两件事（2026-10-03 用户要求）：

**① 随包版本表** —— 「那个一键启动检查更新**还是要加**，但是是**随包资源里配一张版本表**，
每次比对那个表，然后**随管理器更新而更新**，对旧版本**没有这个表，如果表不存在就跳过**」。

**② 没 token 时直连禁止并发** —— 「**直连应该在没有 ghtoken 的时候禁止并发**」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from endfieldmodcontroller import component_versions as CV
from endfieldmodcontroller import fastnet as F


# ── ① 版本表 ────────────────────────────────────────────────────────────────
def test_table_file_exists_and_is_valid() -> None:
    """表文件在仓库里、是合法 JSON、含 builtin/external 两段。"""
    path = Path(__file__).resolve().parents[1] / "endfieldmodcontroller" / "component_versions.json"
    assert path.is_file(), "随包版本表不存在"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "builtin" in data and "external" in data
    assert "XXMI" in data["builtin"], "内置段里应当有 XXMI"


def test_load_returns_dict() -> None:
    data = CV.load()
    assert isinstance(data, dict)
    assert data, "仓库里的表应当能读到内容"


def test_outdated_flags_only_newer() -> None:
    """只有"表里比本机新"的才算待更新；相同/更新的不算。"""
    table = CV.load()
    xxmi_latest = table["builtin"]["XXMI"]["latest"]
    equal = {"XXMI": xxmi_latest}
    assert CV.outdated(equal) == [], "版本相同不该报待更新"
    newer = {"XXMI": "v0.0.1"}
    hits = CV.outdated(newer)
    assert any(h["key"] == "XXMI" for h in hits), f"v0.0.1 应当被报待更新：{hits}"


def test_outdated_skips_missing_local_version() -> None:
    """本机没装（没有版本）**不算**待更新 —— 那是依赖页"安装缺失"的事。"""
    assert CV.outdated({}) == []


def test_outdated_skips_blank_table_entry(monkeypatch) -> None:
    """表里留空的条目要跳过（避免误报）。"""
    fake = {"builtin": {"XXMI": {"latest": ""}}, "external": {}}
    monkeypatch.setattr(CV, "load", lambda: fake)
    assert CV.outdated({"XXMI": "v1.0.0"}) == []


def test_missing_table_means_skip(monkeypatch) -> None:
    """★ **旧版本没有这张表 ⇒ 跳过**（不报错、不阻塞、不误报）。"""
    monkeypatch.setattr(CV, "_table_path", lambda: None)
    assert CV.load() == {}
    assert CV.outdated({"XXMI": "v1.0.0"}) == []


def test_broken_table_means_skip(monkeypatch, tmp_path: Path) -> None:
    """表文件坏了也当"没有"处理，绝不能因此让启动流程报错。"""
    bad = tmp_path / "component_versions.json"
    bad.write_text("{ 这不是 JSON", encoding="utf-8")
    monkeypatch.setattr(CV, "_table_path", lambda: bad)
    assert CV.load() == {}
    assert CV.outdated({"XXMI": "v1.0.0"}) == []


def test_version_tuple_handles_v_prefix() -> None:
    assert CV._ver_tuple("v2.3.8") == (2, 3, 8)
    assert CV._ver_tuple("6.8.0.2155") == (6, 8, 0, 2155)
    assert CV._ver_tuple("") == ()
    assert CV._ver_tuple("v2.3.8") > CV._ver_tuple("v2.2.1")


# ── ② 直连并发要 token ──────────────────────────────────────────────────────
GH = ("https://github.com/jing-hy/EndfieldModController/releases/download/"
      "v1.0.3/EndfieldModController.exe")
MIRROR = "https://ghproxy.net/" + GH


def test_direct_denied_without_token(monkeypatch) -> None:
    """★ 没 token ⇒ 直连禁止并发（GitHub 按 IP 限流，开并发更容易被拒）。"""
    F._TOKEN_CACHE[0] = None
    monkeypatch.setattr(F, "_has_github_token", lambda: False)
    assert F._may_parallel(GH) is False, "没 token 时直连不该允许并发"


def test_direct_allowed_with_token(monkeypatch) -> None:
    """有 token ⇒ 直连允许并发（用户实测 6.3 倍）。"""
    monkeypatch.setattr(F, "_has_github_token", lambda: True)
    assert F._may_parallel(GH) is True


def test_mirror_never_needs_token(monkeypatch) -> None:
    """★ 镜像走第三方中转、不计 GitHub 的 IP 限流 ⇒ **永远允许并发**。"""
    monkeypatch.setattr(F, "_has_github_token", lambda: False)
    assert F._may_parallel(MIRROR) is True, "镜像不该因为没 token 被禁止并发"


def test_is_github_host_recognises_only_real_github() -> None:
    assert F._is_github_host("github.com") is True
    assert F._is_github_host("objects.githubusercontent.com") is True
    assert F._is_github_host("ghproxy.net") is False
    assert F._is_github_host("gh-proxy.com") is False


def test_token_cache_is_used(monkeypatch) -> None:
    """token 判据要缓存，别每次都去读注册表。"""
    calls = {"n": 0}

    def fake_token():
        calls["n"] += 1
        return ("abc", "test")

    import endfieldmodcontroller.github as gh

    monkeypatch.setattr(gh, "token", fake_token)
    F._TOKEN_CACHE[0] = None
    assert F._has_github_token() is True
    assert F._has_github_token() is True
    assert calls["n"] == 1, f"应当只读一次，实际 {calls['n']} 次"
