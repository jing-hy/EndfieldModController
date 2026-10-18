# SPDX-License-Identifier: GPL-3.0-or-later
"""RabbitFX 内置升级 / 上游版本 / GameBanana 选文件（2026-10-18）。

用户原话：「把内置的更新一下，https://gamebanana.com/mods/651557」，随后
「改完直接release，这个插件要接进依赖更新检查」，再补
「是发布前检查、启动前检查和下载更新时检查」。

这里钉住四件事：
  ① `_latest_gamebanana_file` 在**钉的文件名失效**时不能退化成"取最新文件"
     ——同一页面上挂着 `examples.zip` / `cnmodfixer…zip`，它们是最新上传的；
  ② 随包旧副本能被安全升级（只升级"逐文件 sha256 对得上随包历史代"的目录），
     升级前整份备份、用户自己改过的目录一律不动；
  ③ 本机版本号从 ini 首页注释读得出（"接进检查"的前提）；
  ④ `latest_upstream()` 走的是同一条选文件判据（主文件，不是示例/工具）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from endfieldmodcontroller import component_versions, dependencies, rabbitfx
from endfieldmodcontroller.config import AppConfig

INI_V26 = "; RabbitFX -Arknights Endfield- Version 2.6\n[TextureOverrideTest]\nrun = old\n"
INI_V28 = "; RabbitFX -Arknights Endfield- Version 2.8\n[TextureOverrideTest]\nrun = new\n"
DELTA = "[deltaTime]\nvalue = 1\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path: Path, text: str) -> None:
    """按**字节**写：`write_text` 在 Windows 上会把 \\n 转成 \\r\\n，算出来的 sha256 对不上。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _profile(files: list[dict]) -> dict:
    return {"_idRow": 651557, "_sName": "EFMI RabbitFX", "_sVersion": "2.8 | 4.6E4", "_aFiles": files}


MAIN = {"_sFile": "28_2d258.zip", "_sVersion": "2.8",
        "_sDescription": "Main File, if unsure which to download get this one",
        "_tsDateAdded": 1792091301, "_sDownloadUrl": "https://gamebanana.com/dl/1849596",
        "_nFilesize": 6204}
EXAMPLES = {"_sFile": "examples.zip", "_sVersion": "",
            "_sDescription": "Example for modders showing how to create mods with RabbitFX",
            "_tsDateAdded": 1792117403, "_sDownloadUrl": "https://gamebanana.com/dl/1850035",
            "_nFilesize": 1978128}
CNTOOL = {"_sFile": "cnmodfixer_faf22.zip", "_sVersion": "2.1",
          "_sDescription": "CN Mod Fixer Tool (Converts CN mods to experimental RabbitFX)",
          "_tsDateAdded": 1792117481, "_sDownloadUrl": "https://gamebanana.com/dl/1850036",
          "_nFilesize": 9589067}
OLD_V26 = {"_sFile": "v26_b2546.zip", "_sVersion": "2.6",
          "_sDescription": "Main File (older)", "_tsDateAdded": 1784980075,
          "_sDownloadUrl": "https://gamebanana.com/dl/1700000", "_nFilesize": 6160,
          "_bIsArchived": True}


class TestGamebananaFilePick:
    """钉死「名字没匹配上」时的选文件判据（2026-10-18 实测坑）。"""

    def test_pinned_name_wins(self) -> None:
        got = dependencies._latest_gamebanana_file(_profile([MAIN, EXAMPLES, CNTOOL]), "28_2d258")
        assert got is MAIN

    def test_stale_pinned_name_falls_back_to_main_file_not_examples(self) -> None:
        # 旧链条钉的是 v26_b2546；上游换成 28_2d258 之后不能再选到 examples.zip/工具
        got = dependencies._latest_gamebanana_file(
            _profile([MAIN, EXAMPLES, CNTOOL, OLD_V26]), "v26_b2546")
        assert got is MAIN, "钉的文件名失效时，必须回落到标了 Main File 的那个"

    def test_no_main_marker_still_skips_tools_and_examples(self) -> None:
        no_marker = dict(MAIN)
        no_marker["_sDescription"] = "RabbitFX v2.8 (zip)"
        got = dependencies._latest_gamebanana_file(
            _profile([no_marker, EXAMPLES, CNTOOL]), "v26_b2546")
        assert got is no_marker

    def test_only_tools_and_examples_returns_none(self) -> None:
        got = dependencies._latest_gamebanana_file(_profile([EXAMPLES, CNTOOL]), "v26_b2546")
        assert got is None, "宁可报错，也不能把示例包/工具当成依赖本体"

    def test_archived_files_are_never_picked(self) -> None:
        got = dependencies._latest_gamebanana_file(_profile([OLD_V26, MAIN]), "v26_b2546")
        assert got is MAIN

    def test_empty_name_contains_prefers_main_file(self) -> None:
        got = dependencies._latest_gamebanana_file(_profile([CNTOOL, MAIN, EXAMPLES]), "")
        assert got is MAIN


class TestLocalVersion:
    def _env(self, tmp_path: Path) -> AppConfig:
        config = AppConfig()
        config._config_path = str(tmp_path / "config.json")
        return config

    def test_reads_version_from_ini_header(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        target = rabbitfx.install_dir(config)
        target.mkdir(parents=True)
        _write(target / "RabbitFX.ini", INI_V28)
        assert rabbitfx.local_version(config) == "2.8"

    def test_missing_or_unversioned_returns_empty(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        assert rabbitfx.local_version(config) == ""
        target = rabbitfx.install_dir(config)
        target.mkdir(parents=True)
        _write(target / "RabbitFX.ini", "[TextureOverride]\nrun = x\n")
        assert rabbitfx.local_version(config) == ""


class TestUpstream:
    def test_latest_upstream_uses_main_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(dependencies, "_fetch_json",
                            lambda url, *a, **k: _profile([EXAMPLES, MAIN, CNTOOL]))
        info = rabbitfx.latest_upstream()
        assert info["version"] == "2.8"
        assert info["file"] == "28_2d258.zip"
        assert info["url"].endswith("/dl/1849596")


class TestBundledUpgrade:
    """内置升版后，库里那份**我们铺过的旧副本**要跟着升；用户自己那份不动。"""

    def _env(self, tmp_path: Path) -> AppConfig:
        config = AppConfig()
        config._config_path = str(tmp_path / "config.json")
        return config

    def _assets(self, config: AppConfig, *, with_v26_history: bool = True) -> Path:
        src = rabbitfx.assets_root(config) / "rabbitfx"
        src.mkdir(parents=True, exist_ok=True)
        _write(src / "RabbitFX.ini", INI_V28)
        _write(src / "deltaTime.ini", DELTA)
        _write(src / "README.txt", "readme v2.8\n")
        (src / "DISABLED").mkdir(exist_ok=True)
        _write(src / "DISABLED" / "ShaderCacheSettings.ini", "cache\n")
        marker = {"key": "RabbitFX", "remote_version": "1792091301",
                  "updated_at": 1792326936, "source": "gamebanana_mod"}
        _write(src / rabbitfx.MARKER_NAME, json.dumps(marker))
        manifest: dict = {"version": 1, "group": "rabbitfx", "mod_version": "2.8",
                          "compression": "none",
                          "files": {
                              "RabbitFX.ini": {"size": 1, "sha256": _sha(INI_V28)},
                              "deltaTime.ini": {"size": 1, "sha256": _sha(DELTA)},
                              "README.txt": {"size": 1, "sha256": _sha("readme v2.8\n")},
                              "DISABLED/ShaderCacheSettings.ini": {"size": 1, "sha256": _sha("cache\n")},
                          }}
        if with_v26_history:
            manifest["history"] = [{"mod_version": "2.6", "gamebanana_file": "v26_b2546.zip",
                                   "files": {
                                       "RabbitFX.ini": {"size": 1, "sha256": _sha(INI_V26)},
                                       "deltaTime.ini": {"size": 1, "sha256": _sha(DELTA)},
                                       "README.txt": {"size": 1, "sha256": _sha("readme v2.8\n")},
                                       "DISABLED/ShaderCacheSettings.ini": {
                                           "size": 1, "sha256": _sha("cache\n")},
                                   }}]
        _write(src / "manifest.json", json.dumps(manifest, ensure_ascii=False))
        return src

    def _old_install(self, config: AppConfig) -> Path:
        target = rabbitfx.install_dir(config)
        (target / "DISABLED").mkdir(parents=True)
        _write(target / "RabbitFX.ini", INI_V26)
        _write(target / "deltaTime.ini", DELTA)
        _write(target / "README.txt", "readme v2.8\n")
        _write(target / "DISABLED" / "ShaderCacheSettings.ini", "cache\n")
        _write(target / rabbitfx.MARKER_NAME,
               json.dumps({"key": "RabbitFX", "remote_version": "1784980075",
                           "updated_at": 1790498395, "source": "gamebanana_mod"}))
        return target

    def test_fresh_install_keeps_manifest_out_of_library(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        self._assets(config)
        result = rabbitfx.ensure_bundled(config)
        assert result["status"] == "installed"
        target = rabbitfx.install_dir(config)
        assert (target / "RabbitFX.ini").read_text(encoding="utf-8") == INI_V28
        assert not (target / "manifest.json").exists()

    def test_old_bundled_copy_is_upgraded_with_backup(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        self._assets(config)
        target = self._old_install(config)
        # 用户启用了 shader cache（根目录多一个文件）——升级时不该被删
        _write(target / "ShaderCacheSettings.ini", "user cache\n")

        result = rabbitfx.ensure_bundled(config)

        assert result["status"] == "updated"
        assert result["from_version"] == "2.6" and result["version"] == "2.8"
        assert (target / "RabbitFX.ini").read_text(encoding="utf-8") == INI_V28
        assert (target / "ShaderCacheSettings.ini").read_text(encoding="utf-8") == "user cache\n"
        backup = Path(result["backup"])
        assert (backup / "RabbitFX" / "RabbitFX.ini").read_text(encoding="utf-8") == INI_V26
        payload = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
        assert payload["status"] == "complete"
        assert payload["from_version"] == "2.6" and payload["to_version"] == "2.8"

    def test_modified_copy_is_never_touched(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        self._assets(config)
        target = self._old_install(config)
        custom = INI_V26 + "; 用户自己改过\n"
        _write(target / "RabbitFX.ini", custom)

        result = rabbitfx.ensure_bundled(config)

        assert result["status"] == "present" and result.get("kept") is True
        assert (target / "RabbitFX.ini").read_text(encoding="utf-8") == custom
        assert not (Path(config.runtime_path) / "backups" / "rabbitfx").exists()

    def test_already_latest_is_present(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        self._assets(config)
        assert rabbitfx.ensure_bundled(config)["status"] == "installed"
        second = rabbitfx.ensure_bundled(config)
        assert second["status"] == "present" and second.get("version") == "2.8"

    def test_foreign_copy_elsewhere_blocks_install(self, tmp_path: Path) -> None:
        config = self._env(tmp_path)
        self._assets(config)
        foreign = Path(config.library_path) / "（重要前置）RabbitFX v24_3d366"
        foreign.mkdir(parents=True)
        _write(foreign / "RabbitFX.ini", INI_V26)
        result = rabbitfx.ensure_bundled(config)
        assert result["status"] == "already_elsewhere"
        assert not rabbitfx.install_dir(config).exists()


class TestRegisteredForChecks:
    """「发布前 / 启动前 / 下载更新」三处检查都要看得到 RabbitFX。"""

    def _env(self, tmp_path: Path) -> AppConfig:
        config = AppConfig()
        config._config_path = str(tmp_path / "config.json")
        return config

    def test_component_versions_reports_rabbitfx(self, tmp_path: Path) -> None:
        from endfieldmodcontroller import updates

        config = self._env(tmp_path)
        target = rabbitfx.install_dir(config)
        target.mkdir(parents=True)
        (target / "RabbitFX.ini").write_text(INI_V28, encoding="utf-8")
        row = updates.component_versions(config)["rabbitfx"]
        assert row["version"] == "2.8" and row["exists"] is True

    def test_version_table_knows_rabbitfx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        table = component_versions.load()
        assert "rabbitfx" in (table.get("external") or {}), (
            "启动前检查读的是这张表：不登记就永远不会有「该更新」提示"
        )

    def test_outdated_reports_rabbitfx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        table = {"external": {"rabbitfx": {"latest": "2.8"}}}
        monkeypatch.setattr(component_versions, "load", lambda: table)
        rows = component_versions.outdated({"rabbitfx": "2.6"})
        assert any(row["key"] == "rabbitfx" for row in rows)