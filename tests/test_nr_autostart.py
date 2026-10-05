"""「NR 与第一人称相机 hook 共存」的回归测试（2026-10-05 定案 + 用户要求全自动）。

## 背景（三件事都必须钉住）

**① 启动前把 NR 压到相机 hook 之后**（`initialize._check_defer_nr_until_camera_hook`）：
DLSS5 的 NR 若抢在「RenoDX Endfield Enhancer 装相机 hook」之前激活，那次 hook 会
`error 8`（分配 trampoline 内存失败）装不上 ⇒ 面板报「不支持相机控制」。
同一台机器的两次运行对照：失败那次 `feature 18 created` 早于相机 hook 46 秒；
成功那次相机 hook 早于 `feature 18 created` 50 秒。
⚠️ 插件会把 `NeuralUplift=1` **写回** ini，所以**每次启动都要压**。

**② 游戏里自动补开 NR**（`nr_autostart`）：用户要的是全自动 —— 等日志出现
`Camera controls installed.` 之后替用户按一次 NR 键；**键位每次都从日志现读**（用户原话：
「模拟按钮每次都去确认下设的是那个键」），NR 已经在出帧就不按（再按会关掉它）。

**③ 不许覆写用户/插件自己绑的快捷键**（反馈者报「管理器会覆写它的快捷键」）：
`_sync_enhancer_section` 以前每次一键启动都把 `ShortcutFirstPerson` 写回 112(F1)。

全部离线：不碰真实游戏目录 / 真实 runtime / 不发真按键。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import hot_reload, initialize, launcher, nr_autostart
from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    (tmp_path / "runtime" / "reshade").mkdir(parents=True, exist_ok=True)
    nr_autostart.reset()
    yield SimpleNamespace(config=config, root=tmp_path,
                          reshade_dir=tmp_path / "runtime" / "reshade",
                          log_path=tmp_path / "runtime" / "reshade" / "ReShade.log")
    nr_autostart.reset()


def _fake_send(monkeypatch, *, ok: bool = True):
    """把真发键换掉，记录调用（测试绝不发真按键）。"""
    calls: list[dict] = []

    def _send(config, vk, **kwargs):
        calls.append({"vk": vk, **kwargs})
        return {"ok": ok, "sent": 2 if ok else 0,
                "message": "ok" if ok else "游戏窗口没能拿到前台"}

    monkeypatch.setattr(hot_reload, "send_key", _send)
    return calls


# ---------------------------------------------------------------------------
# ① 键位：**每次都从日志现读**，不写死 F6
# ---------------------------------------------------------------------------
def test_key_read_from_log_hotkeys_line(env):
    text = ("12:00:01 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: RenoDX DLSS5 Generic v4.7 "
            "(build Sep  2 2026) loaded (hotkeys: NR toggle F8, screenshot F5) | EnableHooks=2")
    vk, why = nr_autostart._resolve_key(text)

    assert vk == 0x77, f"应当读日志里的 F8，而不是写死 F6（{why}）"
    assert "F8" in why


def test_key_falls_back_with_reason_when_line_missing(env):
    vk, why = nr_autostart._resolve_key("（日志里没有那行）")

    assert vk == nr_autostart.VK_F6
    assert "没有" in why and "F6" in why          # 读不到也要说清"用了默认值"


def test_key_unknown_name_falls_back_with_reason(env):
    vk, why = nr_autostart._resolve_key("loaded (hotkeys: NR toggle MOUSEX99, screenshot F5)")

    assert vk == nr_autostart.VK_F6
    assert "认不出" in why


# ---------------------------------------------------------------------------
# ② 状态机：等相机 hook → 按一次；NR 已在出帧就不按
# ---------------------------------------------------------------------------
def test_waits_until_camera_hook_installed(env, monkeypatch):
    calls = _fake_send(monkeypatch)
    env.log_path.write_text("12:00:02 | INFO | Registered add-on \"RenoDX: ...\"\n",
                            encoding="utf-8")
    nr_autostart.arm(env.config)

    result = nr_autostart.poll(env.config)

    assert result["action"] == "wait" and calls == []


def test_presses_once_after_camera_hook(env, monkeypatch):
    calls = _fake_send(monkeypatch)
    nr_autostart.arm(env.config)
    env.log_path.write_text(
        "12:00:02 | INFO | ... (hotkeys: NR toggle F6, screenshot F5) |\n"
        "12:00:10 | INFO | [RenoDX: Arknights Endfield Enhancer] Endfield enhancer: "
        "Camera controls installed.\n",
        encoding="utf-8")

    first = nr_autostart.poll(env.config)
    second = nr_autostart.poll(env.config)

    assert first["action"] == "sent" and first["vk"] == nr_autostart.VK_F6
    assert len(calls) == 1, "只许按一次"
    assert second["action"] == "skip"


def test_does_not_press_when_nr_already_rendering(env, monkeypatch):
    """NR 已经在出帧（多半用户自己开的）⇒ 再按一次会把它**关掉**，所以不按。"""
    calls = _fake_send(monkeypatch)
    nr_autostart.arm(env.config)
    env.log_path.write_text(
        "[RenoDX: Arknights Endfield Enhancer] Endfield enhancer: Camera controls installed.\n"
        "[DLSS 5 Neural Rendering] DLSS5 Generic: feature 18 created via the signed snippet\n",
        encoding="utf-8")

    result = nr_autostart.poll(env.config)

    assert result["action"] == "skip" and result["reason"] == "nr_active"
    assert calls == []


def test_retries_when_window_not_foreground(env, monkeypatch):
    """窗口没拿到前台 ⇒ **不置 sent**，下一轮自己重试（用户切回游戏就好了）。"""
    calls = _fake_send(monkeypatch, ok=False)
    nr_autostart.arm(env.config)
    env.log_path.write_text("Endfield enhancer: Camera controls installed.\n", encoding="utf-8")

    first = nr_autostart.poll(env.config)
    second = nr_autostart.poll(env.config)

    assert first["action"] == "retry" and second["action"] == "retry"
    assert len(calls) == 2, "没成功就该继续重试"


def test_switch_off_means_no_action(env, monkeypatch):
    calls = _fake_send(monkeypatch)
    env.config.auto_enable_nr_after_camera_hook = False
    nr_autostart.arm(env.config)
    env.log_path.write_text("Endfield enhancer: Camera controls installed.\n", encoding="utf-8")

    result = nr_autostart.poll(env.config)

    assert result["action"] == "skip" and calls == []


# ---------------------------------------------------------------------------
# ③ 启动前把 NR 压成 0（每次都要压 —— 插件会写回 1）
# ---------------------------------------------------------------------------
def _write_ini(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_defers_nr_before_launch(env):
    ini = env.reshade_dir / "ReShade.ini"
    _write_ini(ini, "[RenoDX.DLSS5]\nEnableHooks=2\nNeuralUplift=1\nNREnableUpscaling=0\n")
    report = initialize.Report()

    initialize._check_defer_nr_until_camera_hook(env.config, report, None)

    text = ini.read_text(encoding="utf-8")
    assert "NeuralUplift=0" in text
    assert "NeuralUplift=1" not in text
    checks = [c for c in report.checks if c["key"] == "dlss5:nr_defer"]
    assert checks and checks[0]["ok"] is True and checks[0]["fixed"] is True, checks
    # 同段其它键与其它段一个字都不许动
    assert "EnableHooks=2" in text and "NREnableUpscaling=0" in text


def test_defer_adds_section_when_missing(env):
    ini = env.reshade_dir / "ReShade.ini"
    _write_ini(ini, "[GENERAL]\nPresetPath=ReShadePreset.ini\n")
    report = initialize.Report()

    initialize._check_defer_nr_until_camera_hook(env.config, report, None)

    text = ini.read_text(encoding="utf-8")
    assert "[RenoDX.DLSS5]" in text and "NeuralUplift=0" in text
    assert "[GENERAL]" in text


def test_defer_is_idempotent(env):
    ini = env.reshade_dir / "ReShade.ini"
    _write_ini(ini, "[RenoDX.DLSS5]\nNeuralUplift=0\n")
    report = initialize.Report()

    initialize._check_defer_nr_until_camera_hook(env.config, report, None)

    checks = [c for c in report.checks if c["key"] == "dlss5:nr_defer"]
    assert checks and checks[0].get("fixed") is not True, "已经是 0 就不算改动"


def test_defer_respects_switch(env):
    ini = env.reshade_dir / "ReShade.ini"
    _write_ini(ini, "[RenoDX.DLSS5]\nNeuralUplift=1\n")
    env.config.auto_enable_nr_after_camera_hook = False
    report = initialize.Report()

    initialize._check_defer_nr_until_camera_hook(env.config, report, None)

    assert "NeuralUplift=1" in ini.read_text(encoding="utf-8"), "开关关掉就不许动"


# ---------------------------------------------------------------------------
# ④ 不覆写用户/插件自己绑的快捷键（反馈者报「管理器会覆写它的快捷键」）
# ---------------------------------------------------------------------------
def _enhancer_pair(tmp_path: Path, target_body: str) -> tuple[Path, Path]:
    source = tmp_path / "dlss5" / "ReShade.ini"
    target = tmp_path / "reshade" / "ReShade.ini"
    _write_ini(source, "[endfield-enhancer]\nCameraEFMICompatibility=1\nLanguage=1\n"
                       "ShortcutFirstPerson=112\n")
    _write_ini(target, target_body)
    return source, target


def test_sync_keeps_user_shortcut(tmp_path):
    """用户把第一人称绑到别的键（113=F2）⇒ 一键启动**不许**把它写回 112。"""
    source, target = _enhancer_pair(
        tmp_path, "[endfield-enhancer]\nCameraEFMICompatibility=0\nLanguage=0\n"
                  "ShortcutFirstPerson=113\n")

    launcher._sync_enhancer_section(source, target)

    text = target.read_text(encoding="utf-8")
    assert "ShortcutFirstPerson=113" in text, "用户自己绑的键被覆写了"
    # 但"功能必需项"照旧同步（为 0 时第一人称会被 EFMI 顶掉）、中文也照旧写回
    assert "CameraEFMICompatibility=1" in text and "Language=1" in text


def test_sync_fills_shortcut_when_zero_or_missing(tmp_path):
    """`0` 在 enhancer 里是"没绑快捷键"，不是用户的选择 ⇒ 应当补上 112。"""
    source, target = _enhancer_pair(tmp_path, "[endfield-enhancer]\nShortcutFirstPerson=0\n")

    launcher._sync_enhancer_section(source, target)

    assert "ShortcutFirstPerson=112" in target.read_text(encoding="utf-8")


def test_sync_adds_shortcut_when_key_absent(tmp_path):
    source, target = _enhancer_pair(tmp_path, "[endfield-enhancer]\nLanguage=1\n")

    launcher._sync_enhancer_section(source, target)

    assert "ShortcutFirstPerson=112" in target.read_text(encoding="utf-8")
