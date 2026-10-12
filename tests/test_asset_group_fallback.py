# SPDX-License-Identifier: GPL-3.0-or-later
"""**只要有一个资产组没有来源，就必须去拉资产包**（2026-10-12，来自反馈者诊断包）。

现场（`diagnostics-20261012-001019`，数据根 `D:\\liulanqixiazai`）：
* 面板显示「未安装 NR 运行时」，ReShade 报
  `Failed to compile '…\\DLSS5_Feed.fx': could not open included file 'ReShade.fxh'`；
* 日志里三条 WARN 每次自检都报、却谁也补不上：
  ```
  WARN 初始化: nvngx:nvngx_dlssnr.dll: … 随包/本地都没有含该架构的运行库（已找到的候选：无）
  WARN 初始化: dlss5:shader_deps: 缺少 DLSS5 shader 依赖 … Shaders/ReShade.fxh、…、TriDither.fxh
  WARN 初始化: game:nvngx_dlssnr.dll: 游戏目录缺该文件，内置副本也没有
  ```

**根因**：他只下了单文件 exe —— exe 里内嵌了 `assets\\dlss5\\`（三个 addon + manifest），
而 `assets\\nvngx\\`（NR 运行库分卷）与 `assets\\dlss5\\shaders|textures`（6 个 ReShade
标准头 + Textures）**只在 `assets-bundle.zip` 里**。旧判据有两处都只看"有没有清单"：

* `fetch_bundle`：`any((PROJECT_ROOT / "assets" / g / MANIFEST_NAME).is_file() …)` ⇒ 内嵌的那份一命中就返回「本地已有 assets」；
* `_ensure_all_locked`：`if not found and allow_fetch` ⇒ `found` 非空 ⇒ 永不触发；

⇒ 缺的组**永远补不上**。现在两处都改成"**每一组都得有来源**"（`missing_asset_groups`）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from endfieldmodcontroller import github, runtime_assets
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """把四个"资产候选根"全部指到 tmp：数据根 / exe 目录 / _MEIPASS / 仓库源码目录。"""
    monkeypatch.setattr(runtime_assets, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_assets, "__file__", str(tmp_path / "pkg" / "runtime_assets.py"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    return type("Env", (), {"config": config, "root": tmp_path})()


def _write_manifest(root: Path, group: str, files: dict | None = None) -> None:
    """造一份组清单（默认带一个假条目 —— 空清单会被判成"没有资产"）。"""
    directory = root / "assets" / group
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"files": files if files is not None else {"fake.addon64": {"size": 1}}}
    (directory / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------- ① 判据：缺哪一组
def test_missing_group_reported_when_only_dlss5_present(env):
    """exe 内嵌 dlss5、没下资产包 ⇒ 必须报出缺 `nvngx`（旧判据在这里返回空列表）。"""
    _write_manifest(env.root, "dlss5")
    assert runtime_assets.missing_asset_groups(env.config) == ["nvngx"]


def test_missing_groups_empty_when_all_present(env):
    _write_manifest(env.root, "dlss5")
    _write_manifest(env.root, "nvngx")
    assert runtime_assets.missing_asset_groups(env.config) == []


# --------------------------------------------------------- ② fetch_bundle 的跳过判据
def test_fetch_bundle_runs_when_a_group_is_missing(env, monkeypatch):
    """**核心回归**：只缺一组时也必须去找 Release（旧判据会直接返回「本地已有 assets」）。"""
    _write_manifest(env.root, "dlss5")
    called: list[bool] = []

    def fake_latest(repo, *, prefer_api=False, ttl=3600):
        called.append(prefer_api)
        raise RuntimeError("测试里不联网")

    monkeypatch.setattr(github, "releases_latest", fake_latest)
    result = runtime_assets.fetch_bundle(env.config)
    assert called, "缺一组时 fetch_bundle 必须真的去查 Release"
    assert result["changed"] is False
    assert "本地已有 assets" not in str(result.get("message") or ""), result


def test_fetch_bundle_skips_when_all_groups_present(env, monkeypatch):
    """两组都在 ⇒ 一个请求都不该发（这条同时守住"别白下载 261 MB"）。"""
    _write_manifest(env.root, "dlss5")
    _write_manifest(env.root, "nvngx")

    def fake_latest(repo, *, prefer_api=False, ttl=3600):
        raise AssertionError("资产齐全时不该查 Release")

    monkeypatch.setattr(github, "releases_latest", fake_latest)
    result = runtime_assets.fetch_bundle(env.config)
    assert result == {"ok": True, "changed": False, "message": "本地已有 assets"}


# --------------------------------------------------------- ③ ensure_all 的触发判据
def test_ensure_all_fetches_bundle_when_a_group_is_missing(env, monkeypatch):
    """`found` 非空（内嵌 dlss5 的清单能读到）但缺 `nvngx` ⇒ 仍要拉资产包。

    旧代码是 `if not found and allow_fetch` ⇒ 这条路径整段跳过（就是反馈者的处境）。
    """
    from endfieldmodcontroller import dependencies

    _write_manifest(env.root, "dlss5")
    fetched: list[bool] = []
    # 第一次问"缺哪组" ⇒ nvngx（触发拉取）；之后 ⇒ 空（表示已补齐，测试不必真下载）
    answers = iter([["nvngx"], [], []])
    monkeypatch.setattr(runtime_assets, "missing_asset_groups", lambda cfg: next(answers, []))
    monkeypatch.setattr(runtime_assets, "manifest_entries",
                        lambda cfg: [("dlss5", env.root / "assets" / "dlss5", "fake.addon64", {})])
    monkeypatch.setattr(runtime_assets, "retire_stale_nr_addons", lambda *a, **k: [])
    monkeypatch.setattr(runtime_assets, "ensure_file",
                        lambda *a, **k: runtime_assets.AssetResult(
                            name=str(a[1]), status="present", message="已在位"))
    monkeypatch.setattr(dependencies, "run_batch_with_retry",
                        lambda steps, worker, on_retry=None: (
                            [("ok", worker(step, 0)) for step in steps], []))

    def fake_fetch(config, *, log=None, force=False):
        fetched.append(force)
        return {"ok": True, "changed": True, "message": "ok:1"}

    monkeypatch.setattr(runtime_assets, "fetch_bundle", fake_fetch)

    results = runtime_assets.ensure_all(env.config)
    assert fetched, "缺一组时 ensure_all 必须去拉资产包"
    assert any(item.name == "fake.addon64" for item in results), results


def test_ensure_all_does_not_fetch_when_nothing_lost(env, monkeypatch):
    """两组都在、清单非空 ⇒ 不乱拉资产包。"""
    _write_manifest(env.root, "dlss5")
    _write_manifest(env.root, "nvngx")
    monkeypatch.setattr(runtime_assets, "retire_stale_nr_addons", lambda *a, **k: [])
    monkeypatch.setattr(runtime_assets, "ensure_file",
                        lambda *a, **k: runtime_assets.AssetResult(
                            name=str(a[1]), status="present", message="已在位"))

    def fake_fetch(config, *, log=None, force=False):
        raise AssertionError("资产齐全时不该拉资产包")

    monkeypatch.setattr(runtime_assets, "fetch_bundle", fake_fetch)
    runtime_assets.ensure_all(env.config)      # 不抛即通过
