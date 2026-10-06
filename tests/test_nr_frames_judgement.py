"""DLSS5「NR 建了特征却一帧不出」判据的回归测试（2026-10-06）。

真实反馈（数据根 `P:\\TOOL`、游戏 `K:\\game\\…`、Windows 10 + RTX 5080）：面板「成功NR帧」
停在 4 不动，`ReShade.log` 里 `feature 18 created` 之后紧跟
`NR workset pool exhausted; preserving game output for this evaluation`
（每帧把游戏自己的画面原样放行）。而当时这条自检有两个毛病，**两个都让它在那台机器上彻底空转**：

① **判据太松** —— 只要日志里出现 `evaluation succeeded` 就算"正常出帧"，而引擎**第一帧**
   就会打 `(count=1, …)`（紧接着就是池耗尽）⇒ 它报的是"正常出帧"；
② **读错文件** —— 它读 `runtime\\dlss5\\ReShade.log`，而生效那份在
   `runtime\\reshade\\ReShade.log`（ReShade 的 `RESHADE_BASE_PATH_OVERRIDE`）⇒
   反馈者诊断包里 `dlss5/ReShade.log` 一直是"按当前配置不存在"，判据每次都走
   「还没有 ReShade.log（没进过游戏，跳过）」。**判据读错文件 = 判据不存在**。

要守住的性质：
* 只看**最后一次运行**（以最后一个 `Initializing crosire's ReShade` 为界）；
* `count=1` **不算**出帧；帧号在增长（`count>1`）才算；
* 出现 `workset pool exhausted` ⇒ 报 `dlss5:nr_frames`（`ok=False`、`manual=True`）；
* 读的是**生效那份**日志（`runtime\\reshade`），不是 `runtime\\dlss5`；
* 诊断包摘要里也能直接看到这条结论（第一轮排查不必再翻全量日志）。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import diagnostics, initialize
from endfieldmodcontroller.config import AppConfig

LAST_RUN = "09:00:00 [1] | INFO | Initializing crosire's ReShade version '6.5.1'\n"

POOL_EXHAUSTED = LAST_RUN + (
    "09:00:14 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: feature 18 created via the "
    "signed snippet after DLSS/DLAA for NR input 3840x2160 -> output 3840x2160 with guides 3840x2160\n"
    "09:00:14 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: inline feature 18 evaluation "
    "succeeded (count=1, NR input 3840x2160 (guides 3840x2160), output 3840x2160 [native])\n"
    "09:00:14 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: created inline NR resources "
    "3840x2160 -> 3840x2160 (native) format=28\n"
    "09:00:14 | WARN | [DLSS 5 Neural Rendering] DLSS5 Generic: NR workset pool exhausted; "
    "preserving game output for this evaluation\n"
)

HEALTHY = LAST_RUN + (
    "09:00:14 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: feature 18 created via the "
    "signed snippet after DLSS/DLAA for NR input 3840x2160 -> output 3840x2160 with guides 3840x2160\n"
    "09:00:14 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: inline feature 18 evaluation "
    "succeeded (count=1, NR input 3840x2160 (guides 3840x2160), output 3840x2160 [native])\n"
    "09:00:15 | INFO | [DLSS 5 Neural Rendering] DLSS5 Generic: inline feature 18 evaluation "
    "succeeded (count=60, NR input 3840x2160 (guides 3840x2160), output 3840x2160 [native])\n"
)


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "root"
    runtime = root / "runtime"
    dlss5 = runtime / "dlss5"
    dlss5.mkdir(parents=True)
    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(root / "library"),
        dlss5_dir=str(dlss5),
        builtin_runtime_dir=str(runtime / "builtin"),
    )
    # 生效那份日志与 dlss5 目录**必须是两个地方** —— 否则这条测试就失去意义了
    assert config.reshade_runtime_path != config.dlss5_path
    return config


def _write_log(config, body, *, where="reshade"):
    base = config.reshade_runtime_path if where == "reshade" else config.dlss5_path
    path = base / "ReShade.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _checks(config):
    report = initialize.Report()
    initialize._check_dlss5_nr_binding(config, report, None)
    return {check["key"]: check for check in report.checks}


def test_pool_exhausted_is_reported_as_failure(env):
    """`count=1` + 池耗尽 ⇒ 必须报 `dlss5:nr_frames`（而不是"正常出帧"）。"""
    _write_log(env, POOL_EXHAUSTED)
    checks = _checks(env)
    assert "dlss5:nr_frames" in checks, "池耗尽没有被报出来（判据又只看 evaluation succeeded 了？）"
    assert checks["dlss5:nr_frames"]["ok"] is False
    assert checks["dlss5:nr_frames"]["manual"] is True
    assert "一帧都没产出" in checks["dlss5:nr_frames"]["message"]
    assert "dlss5:nr_binding" not in checks, "不该同时说它正常"


def test_growing_frame_count_is_healthy(env):
    """帧号在涨（count=60）⇒ 才算正常出帧，且不报失败项。"""
    _write_log(env, HEALTHY)
    checks = _checks(env)
    assert checks["dlss5:nr_binding"]["ok"] is True
    assert "60" in checks["dlss5:nr_binding"]["message"]
    assert "dlss5:nr_frames" not in checks


def test_judgement_reads_the_effective_log(env):
    """日志只在 `runtime\\reshade` 下 ⇒ 仍必须判得出来（钉住"读对文件"）。"""
    path = _write_log(env, POOL_EXHAUSTED, where="reshade")
    assert not (env.dlss5_path / "ReShade.log").exists()
    checks = _checks(env)
    assert "dlss5:nr_frames" in checks, f"没有读到 {path}（判据又去读 dlss5 目录了？）"
    assert "还没有 ReShade.log" not in checks.get("dlss5:nr_binding", {}).get("message", "")


def test_only_last_run_counts(env):
    """老日志里的池耗尽不能拿来吓人 —— 只看最后一次运行。"""
    body = POOL_EXHAUSTED + LAST_RUN + HEALTHY.split(LAST_RUN, 1)[1]
    _write_log(env, body)
    checks = _checks(env)
    assert checks["dlss5:nr_binding"]["ok"] is True
    assert "dlss5:nr_frames" not in checks


def test_diagnosis_summary_carries_the_verdict(env):
    """诊断包摘要里要能一眼看到结论 + 现场原文（第一轮排查不必翻全量日志）。"""
    _write_log(env, POOL_EXHAUSTED)
    text = "\n".join(diagnostics._nr_frames_summary(env))
    assert "池耗尽=是" in text
    assert "一帧都没产出" in text
    assert "workset pool exhausted" in text          # 现场原文
    assert "与设置无关" in text                       # 明确告诉用户别再折腾设置


def test_diagnosis_summary_marks_healthy(env):
    _write_log(env, HEALTHY)
    text = "\n".join(diagnostics._nr_frames_summary(env))
    assert "正常出帧" in text
    assert "一帧都没产出" not in text
