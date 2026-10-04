"""第一人称默认项要写进 **ReShade 实际读的那份 ini**。

2026-10-03 用户反馈「第一人称视角不会自动配置」：`core.py` 给游戏进程设了
`RESHADE_BASE_PATH_OVERRIDE` = `runtime\\reshade`，ReShade 读的是**那一份**
`ReShade.ini`；而初始化只维护 `dlss5\\ReShade.ini`。于是 addon 首次运行把**出厂值
（全 0）**写进生效的那份后，`CameraEFMICompatibility` / `ShortcutFirstPerson` 等
在生效文件里全是 0 —— 表现为"面板里点按钮也没反应"。

`launcher._sync_enhancer_section` 负责把关键项从源同步到目标，这里钉住它。
"""
from __future__ import annotations

from pathlib import Path

from endfieldmodcontroller import launcher, reshade_integration
from endfieldmodcontroller.config import AppConfig

SOURCE = """[endfield-enhancer]
CameraEFMICompatibility=1
CameraFirstPersonDialogue=1
CameraFirstPersonMovement=0
Language=1
ShortcutFirstPerson=112
Uncensor=0

[OVERLAY]
Window=
"""

TARGET = """[endfield-enhancer]
CameraEFMICompatibility=0
CameraFirstPersonDialogue=0
CameraFirstPersonMovement=0
Language=1
ShortcutFirstPerson=0
Uncensor=0

[OVERLAY]
Window=
"""


def _v(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return "<missing>"


def test_syncs_only_the_keys_that_differ(tmp_path):
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text(TARGET, encoding="utf-8")

    # CameraEFMICompatibility / CameraFirstPersonDialogue / ShortcutFirstPerson 三项不同
    assert launcher._sync_enhancer_section(src, dst) == 3
    assert _v(dst, "CameraEFMICompatibility") == "1"
    assert _v(dst, "CameraFirstPersonDialogue") == "1"
    assert _v(dst, "ShortcutFirstPerson") == "112"
    # 源里本来就是 0、目标也是 0 的项不该被动；也不该越界改别的段
    assert _v(dst, "Uncensor") == "0"


def test_no_change_is_reported_as_zero(tmp_path):
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text(SOURCE, encoding="utf-8")
    assert launcher._sync_enhancer_section(src, dst) == 0


def test_missing_files_are_ignored(tmp_path):
    """任何一份不存在都不该抛异常（首次运行时那份 ini 可能还没生成）。"""
    existing = tmp_path / "a.ini"
    existing.write_text(SOURCE, encoding="utf-8")
    assert launcher._sync_enhancer_section(existing, tmp_path / "nope.ini") == 0
    assert launcher._sync_enhancer_section(tmp_path / "nope.ini", existing) == 0


# ---------------------------------------------------------------------------
# 2026-10-04：用户报「第一人称的中文没了」—— 上面那套同步**整段都没生效过**
# ---------------------------------------------------------------------------
# 现场：生效那份（`runtime\reshade\ReShade.ini`，由 `RESHADE_BASE_PATH_OVERRIDE` 决定）
# 里是 addon 写的出厂值 `Language=0`，旁边**从来没有** `.bak-before-enhancer-sync`
# （= 同步一次都没改过它）。两个原因叠在一起：
#   ① 顺序：`prepare_reshade_runtime()` 跑在 `initialize` **之前**，而那时源
#      `dlss5\ReShade.ini` 还没被重建（日志原话：`面板字体: 没有 …dlss5\ReShade.ini`）
#      ⇒ 同步拿到"源不存在"直接返回 0，**静默空转**；
#   ② 判据：旧实现只在目标**已经有这个段、且那个键已经存在**时才改写 ⇒
#      初始化重建后的生效那份**整段都没有** `[endfield-enhancer]`，一个键都补不上。


def test_missing_section_is_created(tmp_path):
    """目标整段都没有 `[endfield-enhancer]` 时，必须**补段 + 补键**。"""
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text("[GENERAL]\nEffectSearchPaths=x\n\n[STYLE]\nFont=\n", encoding="utf-8")

    changed = launcher._sync_enhancer_section(src, dst)

    assert changed > 0
    text = dst.read_text(encoding="utf-8")
    assert "[endfield-enhancer]" in text
    assert _v(dst, "Language") == "1"
    assert _v(dst, "CameraEFMICompatibility") == "1"
    assert "[STYLE]" in text and "EffectSearchPaths=x" in text      # 别的段不能被吃掉


def test_missing_key_is_added(tmp_path):
    """段在、但缺 `Language` 这个键时也要补上（addon 只写它知道的键）。"""
    src = tmp_path / "src.ini"
    dst = tmp_path / "dst.ini"
    src.write_text(SOURCE, encoding="utf-8")
    dst.write_text("[endfield-enhancer]\nCameraEFMICompatibility=1\n", encoding="utf-8")

    assert launcher._sync_enhancer_section(src, dst) >= 1
    assert _v(dst, "Language") == "1"


def _config(tmp_path: Path):
    (tmp_path / "runtime" / "reshade").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runtime" / "dlss5").mkdir(parents=True, exist_ok=True)
    cfg = AppConfig()
    cfg._config_path = str(tmp_path / "config.json")
    cfg.data_root = str(tmp_path)
    return cfg


def test_effective_ini_reports_missing_source_instead_of_silence(tmp_path):
    """源还没生成时**如实报出来**（今天是静默返回 0，连日志都没有）。"""
    cfg = _config(tmp_path)
    result = launcher.sync_effective_reshade_ini(cfg)
    assert result["ok"] is False
    assert "源 ini" in result["reason"]


def test_effective_ini_created_from_source_when_absent(tmp_path):
    """生效那份不存在时直接从配好的源复制 —— 否则 ReShade 会自建一份**出厂值**。"""
    cfg = _config(tmp_path)
    cfg.dlss5_ini_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.dlss5_ini_path.write_text(SOURCE, encoding="utf-8")

    result = launcher.sync_effective_reshade_ini(cfg)

    assert result["ok"] is True and result["created"] is True
    target = cfg.reshade_runtime_path / "ReShade.ini"
    assert target.is_file() and _v(target, "Language") == "1"


def test_effective_ini_fixes_language_written_back_by_addon(tmp_path):
    """**顺序回归**（今天那次反馈的核心）：源不存在时先调用=空转；源就绪后再调用必须纠正。"""
    cfg = _config(tmp_path)
    target = cfg.reshade_runtime_path / "ReShade.ini"
    target.write_text(
        "[endfield-enhancer]\nCameraEFMICompatibility=0\nLanguage=0\nShortcutFirstPerson=0\n",
        encoding="utf-8",
    )
    assert launcher.sync_effective_reshade_ini(cfg)["ok"] is False     # initialize 还没跑
    assert _v(target, "Language") == "0"

    cfg.dlss5_ini_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.dlss5_ini_path.write_text(SOURCE, encoding="utf-8")            # initialize 重建了源
    result = launcher.sync_effective_reshade_ini(cfg)

    assert result["ok"] is True and result["enhancer"] >= 1
    assert _v(target, "Language") == "1"
    assert _v(target, "ShortcutFirstPerson") == "112"


def test_panel_font_can_target_the_effective_ini(tmp_path, monkeypatch):
    """字体也要能写到**生效那份**（以前只写 dlss5 那份 ⇒ 中文画成方块）。"""
    cfg = _config(tmp_path)
    target = cfg.reshade_runtime_path / "ReShade.ini"
    target.write_text("[STYLE]\nFont=\n", encoding="utf-8")
    fonts = tmp_path / "windows" / "Fonts"
    fonts.mkdir(parents=True)
    (fonts / "msyh.ttc").write_bytes(b"fake-font")
    monkeypatch.setenv("WINDIR", str(tmp_path / "windows"))

    result = reshade_integration.ensure_panel_font(cfg, ini=target)

    assert result["changed"] is True
    assert "msyh.ttc" in target.read_text(encoding="utf-8")
