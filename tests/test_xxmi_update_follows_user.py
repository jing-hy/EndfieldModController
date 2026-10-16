# SPDX-License-Identifier: GPL-3.0-or-later
"""「更新要打到你指向的那份 XXMI」（2026-10-16 用户原话：「只要指向的 xxmi 就也包含更新」）。

**背景**（反馈者诊断包 `diagnostics-20261015-233155`）：`xxmi_launcher` 指向 `D:\\XXMI` 时，
我们一直只更新内置副本 `runtime\\builtin\\XXMI`（那是 issue #4 的约定：不许劫持他填的路径）
⇒ 依赖页显示「XXMI 已安装 v2.4.7」，而他启动游戏用的那份仍记着 `deployed_version = 2.4.1`
—— 更新了 58 MB，**他实际在跑的那份一点没变**，用户看到的结论是「更新不了 / 更新了没用」。

**同族的第二个缺陷**：`updates._builtin_local_version()` 对 `XXMI-Libs` / `EFMI`
既读错了目录（一律读 XXMI 根）、又读错了 marker 键（读 `XXMI-Libs_version`，
而 `runtime_deps` 写进去的键一直是 `version`）⇒ 本地版本恒为空串 ⇒ 依赖页对这两项
**永远不说有新版**（`update_available` 恒 False）。
"""
from __future__ import annotations

import json

import pytest

from endfieldmodcontroller import launcher, runtime_deps, updates
from endfieldmodcontroller.config import AppConfig


def _config(tmp_path, *, launcher_exe: str = "") -> AppConfig:
    """数据根 / 库 / 游戏目录全在 tmp 下；`launcher_exe` 就是用户填的 `xxmi_launcher`。"""
    runtime = tmp_path / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(tmp_path / "library"),
        builtin_runtime_dir=str(runtime / "builtin"),
        dlss5_dir=str(runtime / "dlss5"),
        poser_dir=str(runtime / "poser"),
        secondary_motion_dir=str(runtime / "secondary_motion"),
        dependency_manifest=str(tmp_path / "dependencies.json"),
        xxmi_launcher=launcher_exe,
    )


def _external_xxmi(tmp_path, name: str = "myxxmi"):
    """造一份"用户自己装的"XXMI（便携布局：`<根>\\Resources\\Bin\\XXMI Launcher.exe`）。"""
    root = tmp_path / name
    bin_dir = root / "Resources" / "Bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "XXMI Launcher.exe"
    exe.write_bytes(b"MZ")
    return root, exe


def _write_marker(root, version: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / runtime_deps.MARKER_NAME).write_text(
        json.dumps({"version": version}), encoding="utf-8")


# ---------------------------------------------------------------------------
# ① 更新目标 = 用户指向的那份
# ---------------------------------------------------------------------------
def test_target_root_follows_the_launcher_the_user_points_at(tmp_path):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))

    target, external = runtime_deps.xxmi_target_root(config)

    assert external is True
    assert target == root, "更新必须打到他实际在用的那份，而不是内置副本"


def test_target_root_is_builtin_when_unset_or_inside_runtime(tmp_path):
    config = _config(tmp_path)
    target, external = runtime_deps.xxmi_target_root(config)
    assert external is False
    assert target == config.builtin_runtime_path / "XXMI"

    builtin_exe = config.builtin_runtime_path / "XXMI" / "Resources" / "Bin" / "XXMI Launcher.exe"
    builtin_exe.parent.mkdir(parents=True, exist_ok=True)
    builtin_exe.write_bytes(b"MZ")
    config.xxmi_launcher = str(builtin_exe)
    target, external = runtime_deps.xxmi_target_root(config)
    assert external is False, "内置路径不算『用户自己那份』"
    assert target == config.builtin_runtime_path / "XXMI"


# ---------------------------------------------------------------------------
# ② 本地版本：各自读自己的 marker（XXMI-Libs / EFMI 曾经恒为空）
# ---------------------------------------------------------------------------
def test_local_versions_come_from_each_components_own_marker(tmp_path):
    config = _config(tmp_path)
    xxmi_root, _ = runtime_deps.xxmi_target_root(config)
    libs = xxmi_root / "Resources" / "Packages" / "XXMI"
    efmi = xxmi_root / "EFMI"
    _write_marker(xxmi_root, "v2.4.7")
    _write_marker(libs, "v1.2.2")
    _write_marker(efmi, "v1.4.8")

    assert updates._builtin_local_version(config, "XXMI") == "v2.4.7"
    assert updates._builtin_local_version(config, "XXMI-Libs") == "v1.2.2", (
        "XXMI-Libs 的版本必须读它自己的 marker（以前读 XXMI 根的 `XXMI-Libs_version` ⇒ 永远空）")
    assert updates._builtin_local_version(config, "EFMI") == "v1.4.8", (
        "EFMI 同理：读 EFMI 目录里的 marker，键是 `version`")


def test_local_versions_follow_the_external_copy(tmp_path):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))
    _write_marker(root, "v2.4.1")
    _write_marker(root / "Resources" / "Packages" / "XXMI", "v1.1.0")

    assert updates._builtin_local_version(config, "XXMI") == "v2.4.1", (
        "依赖页必须显示他实际在用的那份的版本")
    assert updates._builtin_local_version(config, "XXMI-Libs") == "v1.1.0"


# ---------------------------------------------------------------------------
# ③ 更新外部那份：写进它的 marker，但**用户配置原样保留**
# ---------------------------------------------------------------------------
def test_update_writes_into_his_copy_and_keeps_his_config(tmp_path, monkeypatch):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))
    (root / "XXMI Launcher Config.json").write_text('{"user": true}', encoding="utf-8")

    monkeypatch.setattr(runtime_deps, "xxmi_launcher_running", lambda: False)
    monkeypatch.setattr(
        runtime_deps, "_resolve_builtin_asset",
        lambda *a, **k: ("http://example.invalid/x.zip", "v9.9.9", "x.zip", ""))

    def fake_extract(url, asset, target, *a, **k):
        (target / "Resources" / "Bin").mkdir(parents=True, exist_ok=True)
        (target / "Resources" / "Bin" / "XXMI Launcher.exe").write_bytes(b"MZ")
        # 便携包里带的是**出厂默认配置** —— 绝不许覆盖用户那份
        (target / "XXMI Launcher Config.json").write_text('{"factory": true}', encoding="utf-8")

    monkeypatch.setattr(runtime_deps, "_download_extract", fake_extract)
    logs: list[str] = []
    monkeypatch.setattr(launcher, "_append_log", lambda config, message: logs.append(str(message)))

    result = runtime_deps.ensure_xxmi(config, force=True)

    assert result.status == "installed"
    assert runtime_deps._read_marker(root).get("version") == "v9.9.9", "marker 要写在他那份里"
    kept = (root / "XXMI Launcher Config.json").read_text(encoding="utf-8")
    assert kept == '{"user": true}', "用户配置被更新包里的出厂默认覆盖了"
    assert any("你正在用的那份" in line for line in logs), "更新目标必须写进日志"


def test_update_refuses_while_xxmi_is_running(tmp_path, monkeypatch):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))
    monkeypatch.setattr(runtime_deps, "xxmi_launcher_running", lambda: True)
    monkeypatch.setattr(
        runtime_deps, "_resolve_builtin_asset",
        lambda *a, **k: ("http://example.invalid/x.zip", "v9.9.9", "x.zip", ""))

    called = {"extract": False}

    def fake_extract(*a, **k):
        called["extract"] = True

    monkeypatch.setattr(runtime_deps, "_download_extract", fake_extract)

    with pytest.raises(RuntimeError, match="正在运行"):
        runtime_deps.ensure_xxmi(config, force=True)
    assert called["extract"] is False, "XXMI 开着时不许动它的文件（会被系统占用）"


# ---------------------------------------------------------------------------
# ④ EFMI 的落点 = 他实际在用的那个目录（XXMI 配置里的 importer_folder）
# ---------------------------------------------------------------------------
def _write_xxmi_config(root, importer_folder: str) -> None:
    (root / "XXMI Launcher Config.json").write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI"},
        "Importers": {"EFMI": {"Importer": {"importer_folder": importer_folder}}},
    }), encoding="utf-8")


def test_efmi_target_uses_the_importer_folder_in_use(tmp_path):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))
    efmi = tmp_path / "EFMI"
    efmi.mkdir()
    (efmi / "d3d11.dll").write_bytes(b"MZ")
    _write_xxmi_config(root, str(efmi))

    target, external = runtime_deps.xxmi_target_root(config)
    assert runtime_deps.efmi_target_root(config, target, external=external) == efmi


def test_efmi_target_never_writes_into_the_mod_library(tmp_path):
    root, exe = _external_xxmi(tmp_path)
    config = _config(tmp_path, launcher_exe=str(exe))
    inside_library = config.library_path / "EFMI"
    inside_library.mkdir(parents=True)
    (inside_library / "d3d11.dll").write_bytes(b"MZ")
    _write_xxmi_config(root, str(inside_library))

    target, external = runtime_deps.xxmi_target_root(config)
    fallback = runtime_deps.efmi_target_root(config, target, external=external)
    assert fallback == root / "EFMI", "配置被指到 Mod 库时必须退回默认布局，绝不往库里铺文件"
