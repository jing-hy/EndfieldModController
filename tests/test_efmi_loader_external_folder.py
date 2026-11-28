# SPDX-License-Identifier: AGPL-3.0-only
"""XXMI 树外的独立 EFMI 安装也要认（2026-11-28 诊断包 diagnostics-20261128-175808）。

现场：XXMI 在 D:/XXMI、EFMI 在 D:/EFMI（XXMI 的 importer_folder=D:/EFMI）。
active_efmi_loader() 里那条"loader 必须在 XXMI 目录树内"的判据把这份**真 loader**
跳过了（日志：注入自检: 跳过 D:/EFMI/d3d11.dll —— 它不在这个 XXMI 的目录里），
于是 EFMI 注入缺 d3d11.dll ⇒ 皮肤 Mod 不生效。

判据改成"结构"：真 EFMI 根带 Core/EFMI，或 Mods/ 与 d3dx.ini 同时存在；
Mod 库里散落的同名 dll 仍然要被挡住（lzh18 现场那条教训不能丢）。
"""
from __future__ import annotations

import json
from pathlib import Path

from endfieldmodcontroller import launcher
from endfieldmodcontroller.config import AppConfig


def _make_xxmi(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "XXMI" / "Resources" / "Bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "XXMI Launcher.exe").write_bytes(b"MZ")
    return bin_dir


def _config(tmp_path: Path, bin_dir: Path, importer_folder: Path) -> AppConfig:
    (bin_dir / "XXMI Launcher Config.json").write_text(json.dumps({
        "Launcher": {"active_importer": "EFMI"},
        "Importers": {"EFMI": {"Importer": {
            "importer_folder": str(importer_folder).replace("\\", "/")}}},
    }, ensure_ascii=False), encoding="utf-8")
    cfg = AppConfig()
    cfg.xxmi_launcher = str(bin_dir / "XXMI Launcher.exe")
    cfg.save(tmp_path / "config.json")
    return cfg


def test_external_efmi_outside_the_xxmi_tree_is_accepted(tmp_path: Path) -> None:
    bin_dir = _make_xxmi(tmp_path)
    efmi = tmp_path / "EFMI"
    (efmi / "Core" / "EFMI").mkdir(parents=True)
    (efmi / "Mods").mkdir()
    (efmi / "d3d11.dll").write_bytes(b"REAL-LOADER")
    (efmi / "d3dx.ini").write_text("[Loader]" + chr(10), encoding="utf-8")
    cfg = _config(tmp_path, bin_dir, efmi)

    picked = launcher.active_efmi_loader(cfg)
    assert picked is not None, "树外的独立 EFMI 安装被当成非法了"
    assert picked.resolve() == (efmi / "d3d11.dll").resolve()


def test_stray_dll_outside_the_tree_is_still_rejected(tmp_path: Path) -> None:
    bin_dir = _make_xxmi(tmp_path)
    stray = tmp_path / "somewhere"          # 既不是 EFMI 根，也不在 XXMI 树内
    stray.mkdir()
    (stray / "d3d11.dll").write_bytes(b"NOT-A-LOADER")
    cfg = _config(tmp_path, bin_dir, stray)

    assert launcher.active_efmi_loader(cfg) is None
