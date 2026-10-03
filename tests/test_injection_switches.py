"""启动页「拨动即装卸」的两个开关必须**落配置**（2026-10-03 用户实测的 "关不掉"）。

**现象**（用户原话：「ShakingBreastManager 乳摇物理效果 已开启 / Endfield Poser 摆姿 / MMD
播放 这两个按钮关不掉」）：点一下开关，后端**确实**把注入卸了（`runtime\\logs` 里有
「卸载乳摇注入 requested from UI」「已停用 Poser：poser.dll → ….disabled」），但界面
立刻又弹回「已开启」。

**根因**：这两个开关走 `apply`（真装卸），但**没写 `secondary_motion_injection` /
`poser_injection`**。而
* 前端 `loadSettings()` 是**从 config 整份重灌**的 ⇒ 动作做了、界面被旧值覆盖回来；
* 后端 `initialize._check_secondary_motion` / `runtime_deps.ensure_poser` 是**按配置**
  决定要不要注入的 ⇒ 下次一键启动照旧装回去。

**不变式（本文件钉住）**：
① 动作成功 ⇒ 配置键跟着变**且落盘**；
② 动作失败 ⇒ 配置**一个字都不改**，并给前端一条能看懂的原因（不再是"未知原因"）；
③ 关掉之后，启动自检**不许**再装回来。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from endfieldmodcontroller import api as A
from endfieldmodcontroller import initialize, poser, secondary_motion
from endfieldmodcontroller.config import AppConfig


def _api(tmp_path: Path) -> A.EndfieldModControllerApi:
    (tmp_path / "runtime").mkdir(parents=True, exist_ok=True)
    (tmp_path / "library").mkdir(parents=True, exist_ok=True)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{}", encoding="utf-8")
    cfg = AppConfig.load(cfg_path)
    cfg.data_root = str(tmp_path)
    cfg.library_dir = "library"
    cfg.save()
    return A.EndfieldModControllerApi(str(cfg_path))


def _reload(path: Path) -> AppConfig:
    return AppConfig.load(path)


# --------------------------------------------------------------- 乳摇
def test_secondary_motion_uninstall_writes_config(tmp_path, monkeypatch):
    """★ 核心回归：关乳摇 = 卸注入 + `secondary_motion_injection=False` 落盘。"""
    api = _api(tmp_path)
    api.config.secondary_motion_injection = True
    api.config.save()
    called: list[str] = []
    monkeypatch.setattr(secondary_motion, "remove_injection",
                        lambda cfg, log=None: (called.append("remove"),
                                               {"ok": True, "actions": ["移除 plugin\\sbm.dll"],
                                                "warnings": []})[1])

    result = api.secondary_motion_uninstall()

    assert called == ["remove"], "动作要真的执行"
    assert result["ok"] is True
    assert result["config"] == {"secondary_motion_injection": False}, result
    assert api.config.secondary_motion_injection is False
    assert _reload(tmp_path / "config.json").secondary_motion_injection is False, \
        "必须落盘：前端 loadSettings() 读的是 config.json"


def test_secondary_motion_install_writes_config(tmp_path, monkeypatch):
    api = _api(tmp_path)
    api.config.secondary_motion_injection = False
    api.config.save()
    monkeypatch.setattr(secondary_motion, "ensure_injection",
                        lambda cfg, log=None: {"ok": True, "actions": ["安装注入 d3dcompiler_47.dll"],
                                               "warnings": [], "injected": True})

    result = api.secondary_motion_install()

    assert result["ok"] is True
    assert result["config"] == {"secondary_motion_injection": True}
    assert _reload(tmp_path / "config.json").secondary_motion_injection is True


def test_secondary_motion_failure_keeps_config_and_explains(tmp_path, monkeypatch):
    """失败时不许把开关状态改成"已关闭"（配置保持原值），且原因不能是空的。"""
    api = _api(tmp_path)
    api.config.secondary_motion_injection = True
    api.config.save()
    monkeypatch.setattr(secondary_motion, "remove_injection",
                        lambda cfg, log=None: {"ok": False, "actions": [],
                                               "warnings": ["移除 d3dcompiler_47.dll 失败: 占用"]})

    result = api.secondary_motion_uninstall()

    assert result["ok"] is False
    assert "占用" in result["message"], f"要把 warnings 变成可读原因，实际：{result}"
    assert api.config.secondary_motion_injection is True
    assert _reload(tmp_path / "config.json").secondary_motion_injection is True


def test_secondary_motion_missing_game_dir_keeps_config(tmp_path, monkeypatch):
    """未定位到游戏目录这种"根本没动手"的失败，配置同样保持原值。"""
    api = _api(tmp_path)
    api.config.secondary_motion_injection = True
    api.config.save()
    monkeypatch.setattr(secondary_motion, "remove_injection",
                        lambda cfg, log=None: {"ok": False, "message": "未定位到游戏目录",
                                               "actions": [], "warnings": []})

    result = api.secondary_motion_uninstall()

    assert result["message"] == "未定位到游戏目录"
    assert api.config.secondary_motion_injection is True


def test_secondary_motion_partial_action_still_records_intent(tmp_path, monkeypatch):
    """做了一半（ok=False 但确实动过手）⇒ **用户的意愿要记下**，别让界面弹回去。

    真实场景：`ensure_injection` 里"注入源缺少 data\\characters.default.json"之类的
    warning 会把 ok 压成 False，但注入其实装上了；如果这时不写配置，下次启动自检会按
    旧配置把它**反向做回去**，用户看到的就是"我明明关了/开了，它自己变回去"。
    """
    api = _api(tmp_path)
    api.config.secondary_motion_injection = False
    api.config.save()
    monkeypatch.setattr(secondary_motion, "ensure_injection",
                        lambda cfg, log=None: {"ok": False, "actions": ["安装注入 d3dcompiler_47.dll"],
                                               "warnings": ["注入源缺少 data\\characters.default.json"]})

    result = api.secondary_motion_install()

    assert result["config"] == {"secondary_motion_injection": True}
    assert _reload(tmp_path / "config.json").secondary_motion_injection is True
    assert result["warnings"], "遗留问题要原样带回去给前端说明"
    assert result["ok"] is False, "动作没做全这件事不能被掩盖"


# --------------------------------------------------------------- Poser
def test_poser_disable_writes_config(tmp_path, monkeypatch):
    """★ 核心回归：关 Poser = 停用 dll + `poser_injection=False` 落盘。"""
    api = _api(tmp_path)
    api.config.poser_injection = True
    api.config.save()
    seen: list[bool] = []
    monkeypatch.setattr(poser, "set_enabled",
                        lambda cfg, enabled, log=None: (seen.append(bool(enabled)),
                                                        {"ok": True, "changed": True,
                                                         "message": "已停用 Poser"})[1])

    result = api.set_poser_enabled(False)

    assert seen == [False]
    assert result["ok"] is True
    assert result["config"] == {"poser_injection": False}
    assert _reload(tmp_path / "config.json").poser_injection is False


def test_poser_enable_writes_config(tmp_path, monkeypatch):
    api = _api(tmp_path)
    api.config.poser_injection = False
    api.config.save()
    monkeypatch.setattr(poser, "set_enabled",
                        lambda cfg, enabled, log=None: {"ok": True, "changed": True,
                                                        "message": "已启用 Poser"})

    result = api.set_poser_enabled(True)

    assert result["config"] == {"poser_injection": True}
    assert _reload(tmp_path / "config.json").poser_injection is True


def test_poser_failure_keeps_config(tmp_path, monkeypatch):
    """游戏在跑、dll 被占用时停用会失败 —— 这时不许把配置改成"已关闭"。"""
    api = _api(tmp_path)
    api.config.poser_injection = True
    api.config.save()
    monkeypatch.setattr(poser, "set_enabled",
                        lambda cfg, enabled, log=None: {"ok": False, "changed": False,
                                                        "message": "停用失败（游戏在运行时文件会被占用，先退出游戏）"})

    result = api.set_poser_enabled(False)

    assert result["ok"] is False
    assert "退出游戏" in result["message"]
    assert _reload(tmp_path / "config.json").poser_injection is True


def test_poser_reopen_does_not_download_when_pack_is_local(tmp_path, monkeypatch):
    """★ 用户实测「mmd 的 Mod 的开关关了之后再点就打不开了」（第二次）。

    本地安装包**已经在位**时，点"开"必须**一个字节都不下**：
    `runtime_deps.ensure_poser` 的 `up_to_date` 短路带着 `not force`，无条件 `force=True`
    等于"每点一次开就重下一遍安装包" —— 网络一慢/一断，开关就还是打不开，
    而用户其实**本地早就装好了**。
    """
    api = _api(tmp_path)
    api.config.poser_injection = False
    api.config.save()
    monkeypatch.setattr(poser, "status", lambda cfg, **kw: {"pack_ready": True})
    called: list[str] = []
    monkeypatch.setattr(poser, "ensure_pack",
                        lambda cfg, log=None, force=False: (called.append("pack"),
                                                            {"ok": True, "status": "up_to_date"})[1])
    monkeypatch.setattr(poser, "ensure_injection",
                        lambda cfg, log=None: (called.append("inject"), {"ok": True, "actions": []})[1])

    result = api.poser_install()

    assert called == ["inject"], f"包已在位就不该碰下载，实际：{called}"
    assert result.get("ok") is not False


def test_poser_reopen_downloads_when_pack_is_missing(tmp_path, monkeypatch):
    """本地真的没有安装包时才下载，并且**必须 force**（绕开"开关关着就跳过"的守卫）。"""
    api = _api(tmp_path)
    api.config.poser_injection = False
    api.config.save()
    monkeypatch.setattr(poser, "status", lambda cfg, **kw: {"pack_ready": False})
    seen: dict[str, object] = {}
    monkeypatch.setattr(poser, "ensure_pack",
                        lambda cfg, log=None, force=False: (
                            seen.update(force=force),
                            {"ok": True, "status": "installed", "version": "0.5.2"})[1])
    monkeypatch.setattr(poser, "ensure_injection", lambda cfg, log=None: {"ok": True, "actions": []})

    api.poser_install()

    assert seen.get("force") is True, "本地没包时必须绕开开关守卫"


def test_ensure_poser_respects_the_switch_only_when_not_forced(monkeypatch):
    """开关守卫只该拦"一键启动"那条路（force=False），别拦显式指令。"""
    from endfieldmodcontroller import runtime_deps

    cfg = AppConfig()
    cfg.poser_injection = False
    result = runtime_deps.ensure_poser(cfg, force=False)
    assert result.status == "skipped"
    assert "已关闭" in result.message


def test_ensure_poser_forced_bypasses_the_switch(tmp_path, monkeypatch):
    """force=True 时**绕过**开关守卫，一路走到"真的去下载"（正是"显式指令=真更新"的语义）。"""
    from endfieldmodcontroller import runtime_deps

    (tmp_path / "plugin").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plugin" / "poser.dll").write_bytes(b"MZ")

    cfg = AppConfig()
    cfg.poser_injection = False
    monkeypatch.setattr(AppConfig, "poser_path", property(lambda self: tmp_path))
    calls: list[str] = []
    monkeypatch.setattr(runtime_deps, "_latest_release_asset",
                        lambda *a, **k: (calls.append("release"),
                                         ("http://example.invalid/x.zip", "9.9.9", "x.zip", ""))[1])

    def _fake_download(*a, **k):
        calls.append("download")
        raise RuntimeError("到此为止（测试不想真下载）")

    monkeypatch.setattr(runtime_deps, "_download_extract", _fake_download)

    with pytest.raises(RuntimeError):
        runtime_deps.ensure_poser(cfg, force=True)

    assert calls == ["release", "download"], f"force=True 必须绕过开关守卫，实际：{calls}"


# --------------------------------------------------------------- 下次启动要听开关的
def test_launch_selfcheck_does_not_reinstall_when_switch_off(monkeypatch):
    """★ 关掉之后，启动自检必须**不再补齐**（否则用户会觉得"关了又自己开了"）。"""
    cfg = AppConfig()
    cfg.secondary_motion_injection = False
    calls: list[str] = []
    monkeypatch.setattr(secondary_motion, "status",
                        lambda cfg: {"injected": False, "plugin_exists": False})
    monkeypatch.setattr(secondary_motion, "ensure_injection",
                        lambda cfg, log=None: (calls.append("install"), {"ok": True, "actions": []})[1])
    monkeypatch.setattr(secondary_motion, "remove_injection",
                        lambda cfg, log=None: (calls.append("remove"), {"ok": True, "actions": []})[1])

    report = initialize.Report()
    initialize._check_secondary_motion(cfg, report, None)

    assert calls == [], f"开关关着还去动注入：{calls}"


def test_launch_selfcheck_cleans_leftover_when_switch_off(monkeypatch):
    """关着但游戏目录里还留着注入 ⇒ 自检顺手卸干净（可重入、不改配置）。"""
    cfg = AppConfig()
    cfg.secondary_motion_injection = False
    calls: list[str] = []
    monkeypatch.setattr(secondary_motion, "status",
                        lambda cfg: {"injected": True, "plugin_exists": True})
    monkeypatch.setattr(secondary_motion, "ensure_injection",
                        lambda cfg, log=None: (calls.append("install"), {"ok": True, "actions": []})[1])
    monkeypatch.setattr(secondary_motion, "remove_injection",
                        lambda cfg, log=None: (calls.append("remove"),
                                               {"ok": True, "actions": ["移除 plugin\\sbm.dll"]})[1])

    report = initialize.Report()
    initialize._check_secondary_motion(cfg, report, None)

    assert calls == ["remove"], calls
