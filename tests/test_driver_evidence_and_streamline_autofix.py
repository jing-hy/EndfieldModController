"""两处 2026-10-07 的补丁，都是"排查时缺判据/缺动作"引出来的。

**① 手动诊断包的 `environment.txt` 必须带显卡驱动** —— 两个入口原本内容不一致：
   崩溃包那份（`crashwatch._environment_text`）带"设备与显卡"段，而**手动导出的诊断包**这份
   （`diagnostics.collect_environment_report`）没有。代价是实测过的：反馈者用**手动包**报
   "启动即退出"，我们手里就**没有他的驱动版本**；而把各家的包对起来看，是一条很干净的
   剂量-反应链（驱动 596.49 崩 / 616.92 能进 / 573.01 崩）—— 这条线因为缺字段一直没露出来。

**② 游戏自带 Streamline 太旧时，要**自动装**随包运行库**（不能只报 `update_available`）。
   判据是现成的：`crashwatch.streamline_manifest_broken()` 读游戏 `Player.log` 里的
   `ota.cpp:329[parseServerManifest] Unexpected line in manifest file`。
   同机实测：旧版那份日志里 10 条、换成随包 2.14.1 后 **0 条**。
"""
from __future__ import annotations

import pathlib

import pytest

from endfieldmodcontroller import crashwatch, diagnostics, runtime_deps
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    (runtime / "dlss5").mkdir(parents=True)
    (runtime / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: runtime / "dlss5"))
    config = AppConfig()
    config._config_path = str(tmp_path / "config.json")
    return config, runtime, tmp_path


# ---------------------------------------------------------------------------
# ① 诊断包要带显卡驱动
# ---------------------------------------------------------------------------

def test_environment_report_includes_gpu_and_driver(env, monkeypatch):
    """★ 手动诊断包的 `environment.txt` 必须含"设备与显卡"段与驱动号。"""
    config, _runtime, _tmp = env

    # 不跑真实 PowerShell（那是几十秒）：只验我们新加的那一段
    monkeypatch.setattr(diagnostics, "_powershell", lambda *a, **k: ("", ""))
    monkeypatch.setattr(diagnostics, "_ENV_REPORT_CACHE", None, raising=False)

    text, err = diagnostics.collect_environment_report(config)
    assert err == "" or err is None
    assert "设备与显卡" in text, "手动诊断包里没有设备段（反馈者的驱动版本就查不到了）"
    assert "驱动" in text, "没有驱动号"
    # ⚠️ 标题只能出现一次（`deviceinfo.summary_lines()` 自带标题，别再叠一条）
    assert text.count("设备与显卡") == 1, f"标题重复：{text.count('设备与显卡')} 处"


def test_device_summary_lines_owns_the_title():
    """钉住"标题由 `deviceinfo` 提供"这个约定，避免以后又叠一条。"""
    from endfieldmodcontroller import deviceinfo

    lines = [line for line in deviceinfo.summary_lines() if line]
    assert lines, "summary_lines 不该为空"
    assert "设备与显卡" in lines[0], f"首行应当是设备段标题：{lines[0][:60]!r}"


# ---------------------------------------------------------------------------
# ② Streamline：判据命中就自动装
# ---------------------------------------------------------------------------

def test_streamline_downloads_when_game_manifest_is_broken(env, monkeypatch):
    """★★ 游戏自带 Streamline 太旧（`Player.log` 有 parseServerManifest 报错）⇒ **自动下载**。

    这时**不算**"静默下 263 MB"—— 是按判据修故障（用户准则：能自动处理的故障不要用提示交付）。
    """
    config, _runtime, _tmp = env
    monkeypatch.setattr(crashwatch, "streamline_manifest_broken",
                        lambda cfg: "**Streamline 的 server manifest 读不懂**（10 条）")

    called: list[str] = []

    def _asset():
        called.append("asset")
        raise AssertionError("已走到下载路径（打桩拦住，证明 force 被判据提升了）")

    monkeypatch.setattr(runtime_deps, "_streamline_asset", _asset)

    with pytest.raises(AssertionError):
        runtime_deps.ensure_streamline(config)


def test_streamline_still_does_not_download_without_evidence(env, monkeypatch):
    """★ 反向对照：判据**没命中**且本地没有 ⇒ 仍然只报"可以安装"，一个字节都不下。

    （这是 2026-10-07 那条"一键启动被 263 MB 拖到 129 秒"的修复，不能被这次改动弄丢。）
    """
    config, _runtime, _tmp = env
    monkeypatch.setattr(crashwatch, "streamline_manifest_broken", lambda cfg: "")
    monkeypatch.setattr(runtime_deps, "_streamline_asset",
                        lambda: (_ for _ in ()).throw(AssertionError("不该下载")))

    result = runtime_deps.ensure_streamline(config)
    assert result.status == "update_available", result
    assert "263" in (result.message or ""), result.message


def test_streamline_forced_still_downloads(env, monkeypatch):
    """依赖页手动点（`force=True`）照旧真的下。"""
    config, _runtime, _tmp = env
    monkeypatch.setattr(crashwatch, "streamline_manifest_broken", lambda cfg: "")
    monkeypatch.setattr(runtime_deps, "_streamline_asset",
                        lambda: (_ for _ in ()).throw(AssertionError("应当下载却没去下")))

    with pytest.raises(AssertionError):
        runtime_deps.ensure_streamline(config, force=True)
