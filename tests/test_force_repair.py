"""「连续启动失败 → 强力修复」的回归测试（2026-10-05 用户要求）。

用户原话：「**如果连续启动三次失败，加个弹窗，做个强力修复功能，一键还原终末地，
          然后清空依赖并重新下载**，注意：**还原终末地需要把其他第三方的也还原掉**」。

要守住的性质：
* **判据**：**崩了**、或**静默闪退**（没活过 120 秒又没正常退出卸载统计）都算一次失败 ——
  只数崩溃的话，2026-10-05 那位反馈者（每次活 20 秒、一条 WER 都没有）**永远等不到弹窗**；
* **计数**：连续 3 次 ⇒ `ready`；**跑通一次就清零**；同一档只提示一次（防骚扰），
  再坏一次（streak 变大）才重新提示；
* **强力修复**：先还原终末地（**连第三方铺的一起搬走** + 补回系统原版），再清空依赖重下；
* **数据安全**：净化失败 ⇒ **中止、什么都不清**；清空时**保留 `game_backup`**（唯一还原点）。

全部离线：不碰真实游戏目录 / 真实 runtime。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import crashwatch, game_clean
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig


def _evidence(*, crash: bool = False, normal_exit: bool = False, alive: float = 0) -> dict:
    """造一份 `collect_evidence` 形状的字典（只放判据用到的字段）。"""
    return {
        "crash_upload": ["upload"] if crash else [],
        "normal_exit": normal_exit,
        "wer_crash": crash,
        "wer_modules": ["dxgi.dll"] if crash else [],
        "process": {"alive_seconds": alive},
    }


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    game = tmp_path / "game"
    game.mkdir()
    (game / "Endfield.exe").write_bytes(b"MZ")
    runtime = root / "runtime"
    (runtime / "_state").mkdir(parents=True)
    config = AppConfig(
        runtime_dir=str(runtime),
        library_dir=str(root / "library"),
        game_exe=str(game / "Endfield.exe"),
        dlss5_dir=str(runtime / "dlss5"),
        builtin_runtime_dir=str(runtime / "builtin"),
        staging_mods_dir=str(runtime / "EFMI" / "Mods"),
        dependency_manifest=str(root / "dependencies.json"),
    )
    config.save(root / "config.json")
    return SimpleNamespace(root=root, game=game, runtime=runtime, config=config,
                           config_path=root / "config.json")


def _api(env, monkeypatch, *, running: bool = False) -> EndfieldModControllerApi:
    api = EndfieldModControllerApi(env.config_path)
    monkeypatch.setattr(api, "game_running", lambda: {"running": running}, raising=False)
    return api


def _write_proxy(path: Path, size: int = 2048) -> None:
    """造一个"看起来像 loader proxy"的文件（判定靠二进制里的标记串）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"[LOADER] started" + b"\x00" * max(0, size - 16))


# --------------------------------------------------------------- 判据
def test_silent_crash_counts_as_failure(env):
    """**「没检测到崩溃」不算成功** —— 静默闪退（活 20 秒、无 WER）必须计数。

    这是本组最关键的一条：反馈者那台每次只活 20 秒、一条 WER 都没有，
    如果判据只认 `is_crash`，他永远等不到这个弹窗。
    """
    outcome = crashwatch.record_launch_result(env.config, _evidence(alive=20))

    assert outcome["failed"] is True and outcome["streak"] == 1


def test_three_failures_trigger_ready(env):
    for _ in range(2):
        crashwatch.record_launch_result(env.config, _evidence(alive=15))
    assert crashwatch.strong_repair_status(env.config)["ready"] is False, "两次还不够"

    crashwatch.record_launch_result(env.config, _evidence(alive=15))

    state = crashwatch.strong_repair_status(env.config)
    assert state["streak"] == 3 and state["threshold"] == 3
    assert state["ready"] is True


def test_prompt_is_once_per_streak(env):
    """同一档只提示一次；再坏一次（档位变大）才重新提示。"""
    for _ in range(3):
        crashwatch.record_launch_result(env.config, _evidence(alive=15))
    crashwatch.mark_strong_repair_prompted(env.config)
    assert crashwatch.strong_repair_status(env.config)["ready"] is False, "同一档不许重复弹"

    crashwatch.record_launch_result(env.config, _evidence(alive=15))
    assert crashwatch.strong_repair_status(env.config)["ready"] is True, "又坏一次应当重新提示"


def test_success_clears_the_streak(env):
    for _ in range(3):
        crashwatch.record_launch_result(env.config, _evidence(alive=15))

    outcome = crashwatch.record_launch_result(env.config, _evidence(normal_exit=True))

    assert outcome["failed"] is False and outcome["streak"] == 0
    assert crashwatch.strong_repair_status(env.config)["ready"] is False


def test_alive_over_two_minutes_counts_as_success(env):
    """活过 120 秒也算跑通（与 `combo_succeeded` 同一口径）。"""
    outcome = crashwatch.record_launch_result(
        env.config, _evidence(alive=crashwatch.COMBO_SUCCESS_ALIVE_SECONDS + 1))
    assert outcome["failed"] is False and outcome["streak"] == 0


def test_corrupt_state_file_does_not_break_anything(env):
    """计数文件写坏了 ⇒ 当"没有记录"，不许因此影响启动。"""
    path = crashwatch.launch_failure_path(env.config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ 这不是 json", encoding="utf-8")

    assert crashwatch.read_launch_failures(env.config)["streak"] == 0
    assert crashwatch.strong_repair_status(env.config)["ready"] is False


# --------------------------------------------------------------- 强力修复
def test_force_repair_cleans_game_then_resets_dependencies(env, monkeypatch):
    """① 还原终末地（连**第三方**铺的一起搬走）→ ② 清空依赖；净化备份必须留着。"""
    # 模拟"别的工具铺的" proxy —— 判据是"原版不会有这个文件"，所以不管谁铺的都该被搬走
    _write_proxy(env.game / "d3dcompiler_47.dll")
    # 净化备份目录：force_repair **必须保留**它（用户唯一能「撤销清除」的东西）
    backup = env.runtime / "game_backup" / "20260101-000000"
    (backup / "files").mkdir(parents=True)
    (backup / "manifest.json").write_text("{}", encoding="utf-8")
    # runtime 里的无关内容应当被清掉
    (env.runtime / "cache").mkdir()

    api = _api(env, monkeypatch)
    result = api.force_repair()

    assert result["ok"] is True, result
    assert result["moved"] >= 1
    # ⚠️ 判据是"**不再是 proxy**"而不是"文件不存在"：`backup_and_clean` 把 proxy 搬走之后
    #    会把**系统原版**补回游戏目录（官方启动器要校验它）—— 那正是"还原终末地"的语义。
    restored = env.game / "d3dcompiler_47.dll"
    if restored.is_file():
        assert restored.read_bytes()[:16] != b"[LOADER] started", "游戏目录里还是 proxy，净化没生效"
    # 被搬走的 proxy 必须留在备份里（红线：备份可被找到）
    assert (Path(result["backup_dir"]) / "files" / "d3dcompiler_47.dll").is_file(), result["backup_dir"]
    assert (env.runtime / "game_backup").is_dir(), "净化备份不许被清掉（唯一还原点）"
    assert not (env.runtime / "cache").exists(), "runtime 里其它内容该清掉"
    assert crashwatch.strong_repair_status(env.config)["streak"] == 0, "修完计数要清零"


def test_force_repair_aborts_when_clean_fails(env, monkeypatch):
    """净化失败 ⇒ **什么都不清**（数据安全红线：失败保留原状）。"""
    (env.runtime / "cache").mkdir()
    api = _api(env, monkeypatch)
    monkeypatch.setattr(game_clean, "backup_and_clean",
                        lambda *a, **k: {"ok": False, "message": "测试：故意失败"})

    result = api.force_repair()

    assert result["ok"] is False and result["aborted"] == "clean_failed"
    assert (env.runtime / "cache").is_dir(), "净化失败时不许清 runtime"


def test_force_repair_refuses_while_game_running(env, monkeypatch):
    """游戏在跑 ⇒ 拒绝（净化要搬走它正占用的 dll，必然留半截现场）。"""
    api = _api(env, monkeypatch, running=True)

    result = api.force_repair()

    assert result["ok"] is False and result["aborted"] == "game_running"
    assert env.runtime.is_dir()


def test_reset_does_not_restore_third_party_back(env, monkeypatch):
    """`restore_first=False`：净化之后**不许**再"还原"把第三方注入放回游戏目录。

    这是顺序陷阱的直接回归：`reset_dependencies_and_redownload` 默认第一步是
    `restore()`（把上次净化搬走的东西**放回**游戏目录），与"还原成原版"方向正好相反。
    """
    _write_proxy(env.game / "d3dcompiler_47.dll")
    api = _api(env, monkeypatch)

    result = api.force_repair()

    assert result["ok"] is True, result
    # 净化搬走的东西留在备份里，但**不能**再作为 proxy 出现在游戏目录
    # （`restore_first=False` 的回归点就在这里：默认那一步会把它们原样放回来）
    restored = env.game / "d3dcompiler_47.dll"
    if restored.is_file():
        assert restored.read_bytes()[:16] != b"[LOADER] started"
    assert result["reset"]["restore"].get("skipped") is True, result["reset"]["restore"]
