# SPDX-License-Identifier: GPL-3.0-or-later
"""离线依赖包（`deps-bundle.zip`）：校验、导入、以及"各安装链路离线优先"。

用户 2026-10-12：「依赖页本来有一个导入随包 zip 的按钮，现在去掉，换成导入依赖包，
放到最上边自动下载依赖旁边，这个适用于**连不上 github** 的，要包含**所有需要下载的**，
然后导入了**自动配置**」。包**不进 Release**、只作应急分发（QQ 群），所以这里只测
"包能不能安全导入 + 导入后装不装得上"，不涉及发布链路。
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from endfieldmodcontroller import offline_deps, runtime_deps
from endfieldmodcontroller.config import AppConfig


def _make_bundle(path: Path, *, payload: bytes = b"XXMI-ZIP", sha: str = "",
                 member: str = "deps/XXMI-Launcher-Portable-v2.4.6.zip",
                 kind: str = "deps-bundle", extra: dict | None = None) -> Path:
    deps = {
        "XXMI": {
            "asset": "XXMI-Launcher-Portable-v2.4.6.zip",
            "version": "v2.4.6",
            "size": len(payload),
            "sha256": sha or hashlib.sha256(payload).hexdigest(),
            "source": "SpectrumQT/XXMI-Launcher",
            "license": "MIT",
        }
    }
    manifest = {"format": 1, "kind": kind, "deps": deps}
    if extra:
        manifest.update(extra)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr(member, payload)
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"), library_dir=str(tmp_path / "library"))
    return type("Env", (), {"config": config, "root": tmp_path})()


# ------------------------------------------------------------------ ① 校验
def test_inspect_accepts_a_good_bundle(tmp_path):
    report = offline_deps.inspect_deps_bundle(_make_bundle(tmp_path / "ok.zip"))
    assert report["ok"] is True, report
    assert report["deps"] == ["XXMI"]


def test_inspect_rejects_wrong_hash(tmp_path):
    """包被换过 / 压坏了 ⇒ 拒绝（导入前是唯一的拦截点）。"""
    report = offline_deps.inspect_deps_bundle(_make_bundle(tmp_path / "bad.zip", sha="0" * 64))
    assert report["ok"] is False
    assert any("sha256" in item for item in report["problems"])


def test_inspect_rejects_missing_member(tmp_path):
    report = offline_deps.inspect_deps_bundle(
        _make_bundle(tmp_path / "missing.zip", member="deps/other.zip"))
    assert report["ok"] is False
    assert any("缺" in item for item in report["problems"])


def test_inspect_rejects_non_deps_bundle(tmp_path):
    """旧的 `assets-bundle.zip`（或随便一个 zip）不该被当成离线依赖包 —— 它走另一条链路。"""
    other = tmp_path / "assets-bundle.zip"
    with zipfile.ZipFile(other, "w") as archive:
        archive.writestr("assets/dlss5/manifest.json", "{}")
    assert offline_deps.is_deps_bundle(other) is False
    assert offline_deps.inspect_deps_bundle(other)["ok"] is False


def test_inspect_rejects_zip_slip(tmp_path):
    bundle = _make_bundle(tmp_path / "slip.zip")
    with zipfile.ZipFile(bundle, "a") as archive:
        archive.writestr("../evil.txt", "x")
    report = offline_deps.inspect_deps_bundle(bundle)
    assert report["ok"] is False
    assert any("不安全" in item for item in report["problems"])


# ------------------------------------------------------------------ ② 导入
def test_import_lands_files_and_index(env):
    result = offline_deps.import_deps_bundle(env.config, _make_bundle(env.root / "b.zip"))
    assert result["ok"] is True, result
    landed = offline_deps.find_asset(env.config, "XXMI-Launcher-Portable-v2.4.6.zip")
    assert landed is not None and landed.is_file(), result
    assert landed.read_bytes() == b"XXMI-ZIP"
    entry = offline_deps.entry_for(env.config, "XXMI")
    assert entry and entry["version"] == "v2.4.6"
    assert offline_deps.is_deps_bundle(env.root / "b.zip") is True


def test_import_refuses_broken_bundle_without_writing(env):
    """校验不过 ⇒ **一个文件都不落盘**（否则会留下"导入看着成功、之后到处报错"的状态）。"""
    result = offline_deps.import_deps_bundle(
        env.config, _make_bundle(env.root / "bad.zip", sha="0" * 64))
    assert result["ok"] is False
    assert offline_deps.find_asset(env.config, "XXMI-Launcher-Portable-v2.4.6.zip") is None
    assert offline_deps.index_entries(env.config) == {}


# ------------------------------------------------------------------ ③ 装了就用它（不联网）
def test_runtime_deps_prefers_offline_asset(env, monkeypatch):
    """离线索引里有 ⇒ `_resolve_builtin_asset` 必须返回本地文件，且**不去查 Release**。"""
    offline_deps.import_deps_bundle(env.config, _make_bundle(env.root / "b.zip"))

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("离线包里已有该组件，不该再查上游 Release")

    monkeypatch.setattr(runtime_deps, "_latest_release_asset", _must_not_be_called)
    source, version, asset_name, digest = runtime_deps._resolve_builtin_asset(
        env.config, "XXMI", runtime_deps.XXMI_REPO, runtime_deps.XXMI_ASSET_PATTERN)
    assert Path(source).is_file()
    assert version == "v2.4.6" and asset_name.endswith(".zip")
    assert digest == hashlib.sha256(b"XXMI-ZIP").hexdigest()


def test_resolve_offline_returns_none_without_index(env):
    assert offline_deps.resolve_offline(env.config, "XXMI") is None
    assert offline_deps.offline_summary(env.config).startswith("没有导入过")
