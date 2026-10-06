"""写注入库之前必须先把 EFMI 的 loader 部署到位（2026-10-06）。

**现场**（反馈者两次运行对照）：
* `13:31:12` 刚"拉起 XXMI 生成配置" → `13:31:27` 启动游戏 ⇒ 注入库里第二条是
  `Resources\\Packages\\XXMI\\d3d11.dll`（❌）⇒ XXMI 的注入请求变成
  `Inject('d3d11.dll, d3d12.dll, d3d11.dll')` ⇒ **第二次注入失败 + 中断整个启动**；
* `13:34:59`（EFMI 已部署）⇒ 第二条是 `EFMI\\d3d11.dll`（✅）⇒ 正常。
⇒ 所以"自检无缺失、却有时打不开"。

`active_efmi_loader()` 在 `EFMI\\d3d11.dll` 不存在时会回退到包目录那份 ——
这在"刚拉起 XXMI、EFMI 还没部署"的那一刻必然发生，而 XXMI 随后自己会用
`EFMI\\d3d11.dll`，于是同一内容、两个路径 ⇒ 去重不掉。

修法：写注入库**之前**先把包目录那份部署过去（XXMI 自己稍后也会做，我们只是提前一步）。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    xxmi = tmp_path / "runtime" / "builtin" / "XXMI"
    (xxmi / "EFMI").mkdir(parents=True)
    packaged = xxmi / "Resources" / "Packages" / "XXMI"
    packaged.mkdir(parents=True)
    (packaged / "d3d11.dll").write_bytes(b"efmi-loader-body")
    monkeypatch.setattr(AppConfig, "xxmi_launcher_path",
                        property(lambda self: xxmi / "Resources" / "Bin" / "XXMI Launcher.exe"))
    monkeypatch.setattr(AppConfig, "efmi_dir", property(lambda self: xxmi / "EFMI"))
    monkeypatch.setattr(AppConfig, "efmi_dll_path",
                        property(lambda self: (xxmi / "EFMI" / "d3d11.dll")
                                 if (xxmi / "EFMI" / "d3d11.dll").is_file()
                                 else (packaged / "d3d11.dll")))
    return AppConfig(), xxmi


def test_deploys_packaged_loader_into_efmi(env):
    """★ 包目录那份要提前部署到 `EFMI\\d3d11.dll` —— 否则注入库会列到另一条路径。"""
    config, xxmi = env
    target = xxmi / "EFMI" / "d3d11.dll"
    assert not target.is_file()

    message = launcher.ensure_efmi_loader_deployed(config, log=None)

    assert target.is_file(), "没有部署 ⇒ active_efmi_loader 还会回退到包目录那份"
    assert target.read_bytes() == b"efmi-loader-body", "内容必须一致（就是同一份 loader）"
    assert "提前部署" in message, message


def test_noop_when_already_deployed(env):
    """已经部署好 ⇒ 一个字都不说、也不重复拷贝。"""
    config, xxmi = env
    target = xxmi / "EFMI" / "d3d11.dll"
    target.write_bytes(b"already-there")
    assert launcher.ensure_efmi_loader_deployed(config, log=None) == ""
    assert target.read_bytes() == b"already-there", "不该被覆盖"


def test_quiet_when_there_is_no_source(env):
    """两份都没有 ⇒ 返回空串（交给上层照旧报错），不抛异常。"""
    config, xxmi = env
    (xxmi / "Resources" / "Packages" / "XXMI" / "d3d11.dll").unlink()
    assert launcher.ensure_efmi_loader_deployed(config, log=None) == ""


def test_active_loader_picks_the_deployed_one(env):
    """部署之后，`active_efmi_loader()` 必须给出 `EFMI\\d3d11.dll`（而不是包目录那份）。"""
    config, xxmi = env
    launcher.ensure_efmi_loader_deployed(config, log=None)
    picked = launcher.active_efmi_loader(config)
    assert picked is not None
    assert picked.parent.name.lower() == "efmi", picked
    assert picked.name == "d3d11.dll"
