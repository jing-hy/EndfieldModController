"""`active_efmi_loader()` 必须验"它到底是不是 EFMI loader"（2026-10-06，lzh18 现场）。

**现场**（诊断包 `diagnostics-20261006-190132`，`C:\\Users\\lzh18`）：
* XXMI 配置里 `[EFMI] importer_folder = 'C:/Users/lzh18/Downloads/library'` —— 被指向了 **Mod 库**；
* 注入库于是被写成 `...\\library\\d3d11.dll`（某个 Mod 自带的 dll，不是 loader）
  ⇒ 启动时报「**dll 损坏**」。

**判据**：EFMI loader 的可靠标志是**它旁边有 `d3dx.ini`**（3DMigoto 的配置；
普通 Mod / Mod 库里不会有这个名字）⇒ 候选取用前必须过这一关。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """造内置 XXMI 布局 + 一个"被指到 Mod 库"的 importer_folder。"""
    root = tmp_path / "XXMI"
    bin_dir = root / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XXMI Launcher.exe").write_bytes(b"MZ")

    real_efmi = root / "EFMI"
    real_efmi.mkdir(parents=True)
    (real_efmi / "d3d11.dll").write_bytes(b"REAL-LOADER")
    (real_efmi / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")

    library = tmp_path / "library"          # 用户的 Mod 库
    library.mkdir(parents=True)
    (library / "d3d11.dll").write_bytes(b"MOD-BUNDLED-DLL")   # ★ 某个 Mod 自带的，没有 d3dx.ini

    return tmp_path, root, bin_dir, real_efmi, library


def _config(tmp_path, bin_dir, library, *, point_importer_at) -> AppConfig:
    cfg_path = bin_dir / "XXMI Launcher Config.json"
    folder = str(point_importer_at).replace("\\", "/")
    cfg_path.write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI"},
        "Importers": {"EFMI": {"Importer": {"importer_folder": folder}}},
    }, ensure_ascii=False), encoding="utf-8")

    cfg = AppConfig()
    cfg.xxmi_launcher = str(bin_dir / "XXMI Launcher.exe")
    cfg.save(tmp_path / "config.json")
    return cfg


def test_importer_folder_pointing_at_mod_library_is_rejected(env):
    """★ 复现 lzh18 现场：importer_folder 指向 Mod 库 ⇒ 不能把库里那个 dll 当 loader。"""
    tmp_path, _root, bin_dir, real_efmi, library = env
    cfg = _config(tmp_path, bin_dir, library, point_importer_at=library)

    picked = launcher.active_efmi_loader(cfg)
    assert picked is not None, "应当回退到常规布局的 EFMI loader，而不是放弃"
    assert picked.resolve() == (real_efmi / "d3d11.dll").resolve(), (
        f"★ 又选中了库里那个 Mod 自带的 dll：{picked} —— 注入它就会报「dll 损坏」"
    )


def test_normal_layout_is_unaffected(env):
    """对照：importer_folder 正常指向 EFMI 时照旧选它（别把正常路径关掉）。"""
    tmp_path, _root, bin_dir, real_efmi, _library = env
    cfg = _config(tmp_path, bin_dir, real_efmi, point_importer_at=real_efmi)

    picked = launcher.active_efmi_loader(cfg)
    assert picked is not None
    assert picked.resolve() == (real_efmi / "d3d11.dll").resolve()
