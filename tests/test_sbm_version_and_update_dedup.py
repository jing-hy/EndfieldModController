r"""乳摇「更新完还说有新版」+「两个一样的动态」的回归测试（2026-10-05 用户实测报的）。

## 症状（用户原话）

「**我启动说依赖要更新，然后更新完启动还是要更新**，另外**下载完成会有两个一样的动态**」。

## 根因一：`version.txt` 只有人读、没人写

版本检测（`secondary_motion._tool_version` 与 `updates._sbm_local_version`）**优先读
`version.txt`**、读不到才退回目录名 —— 而更新逻辑（`import_pack`）**从来不写它**。
于是目录里一旦留着旧版本号（用户那台是 `…\secondary_motion\version.txt` = `v2.3.5`），
就**永远**被认成旧版：每次启动都报"有新版"，点更新也永远好不了
（现场：`sbm.dll` 真的换了、旧文件进了 `_backup_…_replaced`，可 `version.txt` 还是 v2.3.5）。
⇒ 修：更新成功后按**安装包文件名**把版本号写进 `version.txt`。

## 根因二：同一秒把同一条"要更新"算了两次

日志铁证：`18:47:18.564` 与 `18:47:18.615` 两条一模一样的
`版本表比对：secondary_motion 2.3.5→3.1.2` ⇒ 前端把同一条提示弹了两遍。
⇒ 修：`pending_component_updates` 加 3 秒缓存，缓存命中**不再重复写日志**。

全部离线：只在 tmp 里造包与目录，不碰真实游戏目录 / 真实 runtime。
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from endfieldmodcontroller import secondary_motion, updates
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _make_pack(tmp_path: Path, version: str) -> Path:
    """造一个最小发布包：`ShakingBreastManager-v<version>-ZH-win-x64.zip`。"""
    name = f"ShakingBreastManager-v{version}-ZH-win-x64"
    src = tmp_path / "src" / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "SecondaryMotion.Manager.exe").write_bytes(b"MZ")
    archive = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(src / "SecondaryMotion.Manager.exe", f"{name}/SecondaryMotion.Manager.exe")
    return archive


@pytest.fixture()
def env(tmp_path):
    tool_root = tmp_path / "runtime" / "secondary_motion"
    tool_root.mkdir(parents=True, exist_ok=True)
    (tool_root / "SecondaryMotion.Manager.exe").write_bytes(b"MZ")
    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    secondary_motion_dir=str(tool_root))
    return {"tmp": tmp_path, "root": tool_root, "config": cfg}


def test_import_pack_records_new_version(env):
    """★ 更新完必须把新版本号写进 `version.txt` —— 否则就是"更新完还说有新版"。"""
    root = env["root"]
    # 现场就是这样：目录里躺着旧版本号
    (root / "version.txt").write_text("v2.3.5", encoding="utf-8")

    result = secondary_motion.import_pack(env["config"], _make_pack(env["tmp"], "9.9.9"),
                                          log=lambda _m: None)

    assert result["ok"] is True, result
    assert result["version"] == "v9.9.9"
    assert (root / "version.txt").read_text(encoding="utf-8").strip() == "v9.9.9", (
        "version.txt 没跟着更新 ⇒ 下次启动还会报「有新版本」")


def test_local_version_reads_the_recorded_value(env):
    """更新后的版本号必须能被**版本检测**读到（否则修了也白修）。"""
    (env["root"] / "version.txt").write_text("v9.9.9", encoding="utf-8")

    assert secondary_motion._tool_version(env["root"]) == "v9.9.9"
    assert updates._sbm_local_version(env["config"]) == "9.9.9"


def test_import_pack_without_version_in_name_keeps_old_value(env):
    """包名里认不出版本 ⇒ **不写**（留旧值也比写个错的强），并且如实记一条日志。"""
    root = env["root"]
    (root / "version.txt").write_text("v2.3.5", encoding="utf-8")
    src = env["tmp"] / "src2" / "plain"
    src.mkdir(parents=True)
    (src / "SecondaryMotion.Manager.exe").write_bytes(b"MZ")
    archive = env["tmp"] / "plain.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(src / "SecondaryMotion.Manager.exe", "plain/SecondaryMotion.Manager.exe")
    logs: list[str] = []

    result = secondary_motion.import_pack(env["config"], archive, log=logs.append)

    assert result["ok"] is True, result
    assert result["version"] == ""
    assert (root / "version.txt").read_text(encoding="utf-8").strip() == "v2.3.5"
    assert any("认不出" in line for line in logs), logs


def test_pending_updates_dedup_within_seconds(tmp_path, monkeypatch):
    """★ 同一轮里连调两次 ⇒ 只算一次、**只写一条日志**（治"两个一样的动态"）。"""
    from endfieldmodcontroller import component_versions, launcher

    cfg = AppConfig(runtime_dir=str(tmp_path / "runtime"),
                    staging_mods_dir=str(tmp_path / "runtime" / "EFMI" / "Mods"))
    cfg.save(tmp_path / "config.json")
    api = EndfieldModControllerApi(tmp_path / "config.json")
    monkeypatch.setattr(component_versions, "outdated",
                        lambda installed: [{"key": "secondary_motion", "display": "乳摇",
                                            "current": "2.3.5", "latest": "3.1.2"}])
    logged: list[str] = []
    monkeypatch.setattr(launcher, "_append_log",
                        lambda _cfg, message: logged.append(str(message)))

    first = api.pending_component_updates()
    second = api.pending_component_updates()

    assert first["outdated"] == second["outdated"]
    assert len([m for m in logged if "版本表比对" in m]) == 1, (
        f"同一轮里同一条提示被写了两遍（用户看到的就是两个一样的动态）: {logged}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
