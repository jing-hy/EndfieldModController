"""staging 完整性自检（2026-10-02）：旧版误删了 shader 汇编 `endif` 的 Mod，必须被发现并按库里的原件重建。

**背景**：0.9.2 之前 `core.sanitize_ini_control_flow()` 会把 `[ShaderRegex*.Pattern.Replace]`
里**要塞进 shader 的汇编 `endif`** 当成 ini 控制流删掉（拿旧实现真跑实测：`RabbitFX.ini`
67 → 5、湿润效果修复 `Shader.ini` 14 → 3、庄方宜两份 `CutoutMask.ini` 各 4 → 0）⇒ 汇编里
`if_nz` 不闭合 ⇒ 驱动着色器编译器当场崩（`nvgpucomp64`）、剔除遮罩失效导致模型不出。

**它只改 staging 副本，库里的原件一直是好的**；但**已经生成过的 staging 会一直带着伤** ——
用户升级到新版后若不重新「一键启动」，游戏读到的仍是坏的，他会以为"新版没用"。
所以自检要主动发现并**自动按库里的原件重建**（用户要求：能自动处理的别让人手动）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from endfieldmodcontroller import activation, core, initialize, launcher
from endfieldmodcontroller.config import AppConfig

# 一份"要塞进 shader 的汇编"（行尾是**字面** \n）——`if_nz` 与 `endif` 配平
GOOD_ASM = (
    "[ShaderRegex000_WetUV.Pattern.Replace]\n"
    "$0\n"
    "resinfo_indexable(texture2d)(float,float,float,float) t80.xyyy, l(0), t80.xyzw\\n\n"
    "if_nz t80.w\\n\n"
    "mov r0, r1\\n\n"
    "endif\\n\n"
)
# 旧版就是这么删的：整行 `endif` 没了 ⇒ 汇编不闭合
BAD_ASM = GOOD_ASM.replace("endif\\n\n", "")
PLAIN_INI = "namespace = Test\n[TextureOverride_x]\nhash = aaaa1111\n"


# --------------------------------------------------------- 判据本身
def test_balanced_asm_is_fine(tmp_path):
    p = tmp_path / "good.ini"
    p.write_text(GOOD_ASM, encoding="utf-8")
    assert core.ini_asm_if_unbalanced(p) is None


def test_truncated_endif_is_detected(tmp_path):
    p = tmp_path / "bad.ini"
    p.write_text(BAD_ASM, encoding="utf-8")
    detail = core.ini_asm_if_unbalanced(p)
    assert detail is not None, "少了 endif 就该被认出来"
    assert detail["if_nz"] == 1 and detail["endif"] == 0 and detail["missing"] == 1


def test_plain_ini_without_asm_is_ignored(tmp_path):
    """普通换装 ini（没有汇编文本）不该被误报 —— 它们本来就没有 if_nz/endif。"""
    p = tmp_path / "plain.ini"
    p.write_text(PLAIN_INI, encoding="utf-8")
    assert core.ini_asm_if_unbalanced(p) is None


def test_ini_control_flow_is_not_confused_with_asm(tmp_path):
    """ini 自己的 `if … endif` 控制流不算汇编：哪怕写成每行带尾注也不能误报。"""
    p = tmp_path / "flow.ini"
    p.write_text(
        "[Present]\nif $mod_enabled\n    post $x = 1\nendif\n",
        encoding="utf-8",
    )
    assert core.ini_asm_if_unbalanced(p) is None


def test_find_unbalanced_scans_tree(tmp_path):
    (tmp_path / "MC_A").mkdir()
    (tmp_path / "MC_A" / "good.ini").write_text(GOOD_ASM, encoding="utf-8")
    (tmp_path / "MC_B").mkdir()
    (tmp_path / "MC_B" / "bad.ini").write_text(BAD_ASM, encoding="utf-8")

    found = core.find_unbalanced_asm_inis(tmp_path)

    assert len(found) == 1, found
    assert found[0]["name"] == "bad.ini" and found[0]["missing"] == 1


# --------------------------------------------------------- 自检行为
@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "library_path", property(lambda self: tmp_path / "library"))
    monkeypatch.setattr(AppConfig, "staging_mods_path", property(lambda self: tmp_path / "Mods"))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "controller_dir",
                        property(lambda self: tmp_path / "runtime" / "controller"))
    monkeypatch.setattr(AppConfig, "effective_selected_mods", property(lambda self: ["mod-1"]))
    for name in ("library", "Mods", "runtime"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(tmp=tmp_path, config=config)


def _stub_stage(monkeypatch):
    calls: list[dict] = []

    def fake(*args, **kwargs):
        calls.append(kwargs)
        return {"patch_count": 1}

    monkeypatch.setattr(activation, "stage_and_prepare", fake)
    monkeypatch.setattr(launcher, "resolve_hotkey_takeover", lambda *a, **k: False)
    return calls


def test_check_staging_rebuilds_when_broken(env, monkeypatch):
    """发现被旧版改坏的 staging → **自动按库里的原件重建**，并说清原因。"""
    calls = _stub_stage(monkeypatch)
    broken_mod = env.config.staging_mods_path / "MC_莱万汀_被改坏的"
    broken_mod.mkdir(parents=True)
    (broken_mod / "WetFX.ini").write_text(BAD_ASM, encoding="utf-8")

    report = initialize.Report()
    initialize._check_staging(env.config, report, None)

    assert calls, "发现被改坏的 staging 就该重建（不能只提示、让用户自己想办法）"
    check = report.checks[-1]
    assert check["ok"] is True and check["fixed"] is True, check
    assert "旧版本" in check["message"] and "endif" in check["message"], check["message"]
    assert "库里的文件一直没动过" in check["message"]
    assert report.actions, "要留下'按库里原件重新生成'的动作记录"


def test_check_staging_keeps_healthy_staging(env, monkeypatch):
    """健康的 staging 不该被重建（省时间，也不打扰用户）。"""
    calls = _stub_stage(monkeypatch)
    ok_mod = env.config.staging_mods_path / "MC_佩丽卡_正常"
    ok_mod.mkdir(parents=True)
    (ok_mod / "a.ini").write_text(GOOD_ASM, encoding="utf-8")

    report = initialize.Report()
    initialize._check_staging(env.config, report, None)

    assert not calls, "健康的 staging 被重建了（多余且危险）"
    assert report.checks[-1]["ok"] is True
    assert "已 staging" in report.checks[-1]["message"]


def test_check_staging_still_stages_when_missing(env, monkeypatch):
    """staging 整个不存在时，老行为不变（照样补齐）。"""
    calls = _stub_stage(monkeypatch)
    report = initialize.Report()
    initialize._check_staging(env.config, report, None)

    assert calls, "没有 staging 目录就该 stage"
    assert report.checks[-1]["fixed"] is True


def test_reports_when_library_source_also_broken(env, monkeypatch):
    """**库里的原件也坏了** → 重建 staging 没意义（只是把坏文件再复制一遍），必须如实报告。

    而且 —— **一个字节都不许动库**（用户的红线：除他自己点「移出 Mod 库」外，任何情况都不动）。
    """
    calls = _stub_stage(monkeypatch)
    lib_mod = env.config.library_path / "WetTest"
    lib_mod.mkdir(parents=True)
    (lib_mod / "WetFX.ini").write_text(BAD_ASM, encoding="utf-8")
    staged = env.config.staging_mods_path / "MC_WetTest_WetTest"
    staged.mkdir(parents=True)
    (staged / "WetFX.ini").write_text(BAD_ASM, encoding="utf-8")

    report = initialize.Report()
    initialize._check_staging(env.config, report, None)

    assert not calls, "库里的原件也坏时重建 staging 只是自欺欺人"
    check = report.checks[-1]
    assert check["ok"] is False and check["manual"] is True, check
    assert "Mod 库" in check["message"], check["message"]
    assert "我们不会动你的 Mod 库" in check["message"]
    # 库一个字节没动
    assert (lib_mod / "WetFX.ini").read_text(encoding="utf-8") == BAD_ASM


def test_rebuilds_when_library_source_is_fine(env, monkeypatch):
    """对照：库里的原件是好的（正常情况）→ 照旧自动重建。"""
    calls = _stub_stage(monkeypatch)
    lib_mod = env.config.library_path / "WetTest"
    lib_mod.mkdir(parents=True)
    (lib_mod / "WetFX.ini").write_text(GOOD_ASM, encoding="utf-8")
    staged = env.config.staging_mods_path / "MC_WetTest_WetTest"
    staged.mkdir(parents=True)
    (staged / "WetFX.ini").write_text(BAD_ASM, encoding="utf-8")   # staging 被旧版改坏

    report = initialize.Report()
    initialize._check_staging(env.config, report, None)

    assert calls, "库里的原件是好的 → 就该重建修好"
    check = report.checks[-1]
    assert check["ok"] is True and check["fixed"] is True, check
    assert "库里的文件一直没动过" in check["message"]
