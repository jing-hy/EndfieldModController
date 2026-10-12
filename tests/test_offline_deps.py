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


# ------------------------------------------------- ④ Poser / Streamline 也要走通（用户要求）
def test_poser_prefers_offline_and_never_queries_upstream(env, monkeypatch):
    """Poser 是**预发布**版（原先必须联网查列表接口）—— 离线包里带了就不许再联网。"""
    payload = b"poser-installer"
    bundle = _make_bundle(
        env.root / "poser.zip", payload=payload, member="deps/Endfield-Poser-v0.5.58-win64.zip",
        extra={})
    # 把清单里的键换成 Poser（asset 名也换）
    with zipfile.ZipFile(bundle) as source:
        manifest = json.loads(source.read("manifest.json").decode("utf-8"))
    manifest["deps"] = {"Poser": {
        "asset": "Endfield-Poser-v0.5.58-win64.zip", "version": "0.5.58",
        "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
        "source": "https://github.com/OedoSoldier/Endfield-Poser", "license": "AGPL-3.0",
    }}
    with zipfile.ZipFile(bundle, "w") as target:
        target.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        target.writestr("deps/Endfield-Poser-v0.5.58-win64.zip", payload)
    offline_deps.import_deps_bundle(env.config, bundle)

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("离线包里已有 Poser，不该再查上游（预发布列表接口）")

    monkeypatch.setattr(runtime_deps, "_latest_release_asset", _must_not_be_called)
    source, version, asset_name, _digest = runtime_deps._resolve_builtin_asset(
        env.config, "Poser", runtime_deps.POSER_REPO, runtime_deps.POSER_ASSET_PATTERN,
        include_prerelease=True)
    assert version == "0.5.58" and asset_name.endswith(".zip")
    assert Path(source).read_bytes() == payload


def test_streamline_installs_from_flat_offline_dlls(env, monkeypatch):
    """Streamline 离线件是"只含 9 个 dll"的**扁平**包 —— 必须照样装到 `runtime\\streamline\\`。"""
    wanted = list(runtime_deps.STREAMLINE_WANTED)
    flat = env.root / "streamline-runtime-2.14.1.zip"
    with zipfile.ZipFile(flat, "w") as archive:      # 扁平：没有 bin\x64 层级
        for name in wanted:
            archive.writestr(name, b"fake-dll:" + name.encode())
    index = {"Streamline": {"asset": flat.name, "version": "v2.14.1", "size": flat.stat().st_size,
                            "sha256": hashlib.sha256(flat.read_bytes()).hexdigest(),
                            "source": "https://github.com/NVIDIA-RTX/Streamline",
                            "license": "MIT", "kind": "streamline-dlls"}}
    offline_deps.save_index(env.config, index)
    (offline_deps.offline_dir(env.config) / flat.name).write_bytes(flat.read_bytes())

    def _must_not_download(*args, **kwargs):
        raise AssertionError("离线包里已有 Streamline，不该再下载 263 MB SDK")

    monkeypatch.setattr(runtime_deps, "_streamline_asset", _must_not_download)
    monkeypatch.setattr(runtime_deps, "crashwatch", None, raising=False)
    result = runtime_deps.ensure_streamline(env.config, force=True)

    target = Path(env.config.runtime_path) / "streamline"
    landed = sorted(item.name for item in target.glob("*.dll"))
    assert landed == sorted(wanted), result
    assert result.status == "installed", result
    for name in wanted:
        assert (target / name).read_bytes() == b"fake-dll:" + name.encode()
