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
    # ⚠️ 本文件测的是**保守模式**那条路（启动前压 0 → 等相机 hook → 自动按 F6）。
    #    2026-10-06 起默认换成了 `start_dlss5_nr_immediately=True`（启动就开），
    #    所以这里**显式退回保守模式**；"启动就开"另有两组专门测试（见文件末尾）。
    config.start_dlss5_nr_immediately = False
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


def test_sync_never_touches_camera_first_person(tmp_path):
    """★ 2026-10-05：**不许覆写用户的第一人称开关状态**。

    用户原话：「**你不要复写我的第一人称开启状态配置**」。它确实是"相机 hook 能不能装上"
    的关键（`0` 时 enhancer 不去装 hook ⇒ 永远等不到 `Camera controls installed.`），
    但**开不开第一人称是用户自己的偏好** —— 一键启动只保证**不去动它**。
    """
    source = tmp_path / "dlss5" / "ReShade.ini"
    target = tmp_path / "reshade" / "ReShade.ini"
    _write_ini(source, "[endfield-enhancer]\nCameraFirstPerson=1\n")
    _write_ini(target, "[endfield-enhancer]\nCameraFirstPerson=0\n")

    launcher._sync_enhancer_section(source, target)

    text = target.read_text(encoding="utf-8")
    assert "CameraFirstPerson=0" in text, "用户设的 0 必须原样保留"
    assert "CameraFirstPerson=1" not in text


# ---------------------------------------------------------------------------
# ⑤ 2026-10-05 加：**「还没走到那一步」与「hook 装失败了」必须分得开**
#
# 用户实测「又测了一次，就是没自动开 nr」。查下来那次 ReShade 日志里 enhancer
# **只打了 "Registered add-on" 一行** —— 既没有 `Camera controls installed.`（成功），
# 也没有 `camera hook installation failed`（失败，游戏 87 秒内没进到场景）。
# 当时的判据只认前者 ⇒ 两种情形都表现为"一直等"，日志里连一条线索都没有。
# ---------------------------------------------------------------------------
def test_hook_failure_is_reported_not_silently_waited(env, monkeypatch):
    """★ 相机 hook 装失败 ⇒ 明确报出来并打住，不许继续默默等。"""
    calls = _fake_send(monkeypatch)
    nr_autostart.arm(env.config)
    env.log_path.write_text(
        "12:00:10 | WARN | [RenoDX: Arknights Endfield Enhancer] Endfield enhancer: "
        "Camera hook installation failed; camera controls disabled.\n", encoding="utf-8")
    lines: list[str] = []

    result = nr_autostart.poll(env.config, log=lines.append)

    assert result["action"] == "skip" and result["reason"] == "hook_failed", result
    assert calls == [], "hook 装失败时绝不能开 NR（NR 抢在前面会把相机控制弄没）"
    assert any("安装失败" in line for line in lines), lines


def test_wait_diagnostic_fires_once_after_timeout(env, monkeypatch):
    """★ 等太久 ⇒ 留一行诊断（说清多半是还没进场景），且**只写一次**不刷屏。"""
    calls = _fake_send(monkeypatch)
    clock = {"now": 1000.0}
    monkeypatch.setattr(nr_autostart.time, "time", lambda: clock["now"])
    nr_autostart.arm(env.config)
    env.log_path.write_text("12:00:02 | INFO | Registered add-on ...\n", encoding="utf-8")
    lines: list[str] = []

    nr_autostart.poll(env.config, log=lines.append)
    assert not any("已等" in line for line in lines), "还没到点不该刷诊断"

    clock["now"] += nr_autostart._WAIT_DIAG_SECONDS + 1
    with env.log_path.open("a", encoding="utf-8") as handle:
        handle.write("12:01:30 | INFO | another line\n")
    nr_autostart.poll(env.config, log=lines.append)
    assert any("已等" in line and "场景" in line for line in lines), lines

    with env.log_path.open("a", encoding="utf-8") as handle:
        handle.write("12:01:40 | INFO | third line\n")
    nr_autostart.poll(env.config, log=lines.append)
    assert sum(1 for line in lines if "已等" in line) == 1, "诊断只写一次，不许刷屏"
    assert calls == []


# ---------------------------------------------------------------------------
# ⑥ 2026-10-06 新默认：**DLSS5 神经渲染启动就开**（不再等相机 hook）
#
# 用户原话：「nr 我不是改了吗，现在应该是不用管 hook」。改成默认之后：
#   * 自检把 `NeuralUplift` 写成 **1**（以前写 0）；
#   * `nr_autostart` **整条停用**（NR 已开，不必等 hook、也不必模拟按键）。
# 为什么可以直接这样：`CameraFirstPerson=1` 时 2026-10-05 已实测定案"NR 启动就开
# 与相机 hook **可以共存**"；`CameraFirstPerson=0` 时 enhancer 根本不装相机 hook，
# 没有东西需要保护（反馈者那台就是因此永远等不到那句话）。
# ---------------------------------------------------------------------------
def test_immediate_mode_writes_neural_uplift_one(env):
    """★ 默认模式：自检把 `NeuralUplift` 写成 **1**（不是 0）。"""
    env.config.start_dlss5_nr_immediately = True
    ini = env.reshade_dir / "ReShade.ini"
    _write_ini(ini, "[RenoDX.DLSS5]\nEnableHooks=2\nNeuralUplift=0\nNREnableUpscaling=0\n")
    report = initialize.Report()

    initialize._check_defer_nr_until_camera_hook(env.config, report, None)

    text = ini.read_text(encoding="utf-8")
    assert "NeuralUplift=1" in text, "启动就开必须写成 1"
    assert "NeuralUplift=0" not in text
    checks = [c for c in report.checks if c["key"] == "dlss5:nr_defer"]
    assert checks and checks[0]["ok"] is True and checks[0]["fixed"] is True, checks
    assert "EnableHooks=2" in text and "NREnableUpscaling=0" in text, "同段其它键不许动"


def test_immediate_mode_skips_autostart_entirely(env, monkeypatch):
    """★ 默认模式：`nr_autostart` 直接跳过（不再等 hook、不再模拟按键）。"""
    calls = _fake_send(monkeypatch)
    env.config.start_dlss5_nr_immediately = True
    nr_autostart.arm(env.config)
    env.log_path.write_text(
        "12:00:02 | INFO | [RenoDX: Arknights Endfield Enhancer] Endfield enhancer: "
        "Camera controls installed.\n", encoding="utf-8")

    result = nr_autostart.poll(env.config)

    assert result["action"] == "skip" and "启动就开" in result["reason"], result
    assert calls == [], "启动就开时不该再模拟按键"


def test_numpad_hotkey_names_are_recognised(env):
    """★ 2026-10-06：小键盘键名要认全 —— 反馈者把 NR 键设成了小键盘键。

    他的日志原文是 `hotkeys: NR toggle NUM`，而当时的键表里没有 `NUM` ⇒
    **退回按了 F6** ⇒ NR 从未被打开（面板停在「成功NR帧 4」，那几帧是误按留下的）。
    """
    for name, want in (("NUM", 0x90), ("NUMLOCK", 0x90), ("NUM0", 0x60), ("NUM9", 0x69),
                       ("NUMPAD5", 0x65), ("NUM+", 0x6B), ("NUM-", 0x6D)):
        vk, why = nr_autostart._resolve_key(f"loaded (hotkeys: NR toggle {name}, screenshot F5)")
        assert vk == want, f"{name} 应当解析成 0x{want:02X}，实际 0x{vk:02X}（{why}）"
        assert "认不出" not in why, f"{name} 不该被当成认不出"
