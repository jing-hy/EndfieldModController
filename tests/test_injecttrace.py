"""`injecttrace`（注入现场时间线）与「资产展开的并发保护」的测试（2026-10-05）。

**为什么要有 `injecttrace`**：用户要求「在一键启动最开始和 xxmi 拉起后和终末地启动后和
终末地关闭和崩溃后**都要收注入列表**」。只抓崩溃那一刻分不出"本来是对的、中途被改坏"
和"一直都是这样" —— 而 `0xC0000135` 恰好有这两种来源（真缺依赖 / 进程内 `LoadLibrary`
失败后异常传播），`expect_missing`（该进进程的两条在不在）就是把它们分开的钥匙。

**为什么要有并发保护**：反馈者 23:50 的日志里出现
「`sha256 校验失败（得到 2d8b3e2f…，期望 e16bcf15…）`」—— 一键启动在两条路径上各展开一次，
而临时文件原先**固定名**，两个线程互踩：一个在算 sha256 时读到另一个正在写的内容。

**要守住的性质**：
* 临时文件路径**每个线程都不同**、且与目标**同目录**（跨盘 `os.replace` 会报 WinError 17）；
* `ensure_all` 与它的实现体分离、外面套着那把锁（第二次进来走"已就位"快路径）；
* 快照带 `phase`/`phase_label`/注入库逐条/游戏目录注入物/`runtime\\dlss5` 状态；
* `record` 增量落盘、`read_all` 能读回、`render` 里五时机与"该进却没进"都写得出来；
* **五个时机在源码里真的都接了**（静态钉住 —— 少接一个，那条时间线就断一节）。
"""
from __future__ import annotations

import inspect
import threading
from pathlib import Path

from endfieldmodcontroller import crashwatch, diagnostics, injecttrace, launcher, runtime_assets


# --------------------------------------------------------------------------- 并发保护
def test_tmp_path_is_unique_and_same_dir(tmp_path):
    """★ 临时文件必须**每个线程都不同**、且与目标同目录。"""
    target = tmp_path / "nvngx_dlssnr.dll"
    seen: list[str] = []

    def worker() -> None:
        seen.append(str(runtime_assets._tmp_path(target)))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(seen)) == len(seen), f"不同线程拿到的临时路径不能重复：{seen}"
    assert str(runtime_assets._tmp_path(target)) not in seen
    for item in seen:
        assert Path(item).parent == tmp_path, "临时文件必须与目标同目录（否则 os.replace 跨盘报错）"
        assert item.endswith(runtime_assets.TMP_SUFFIX)


def test_ensure_all_serializes_its_body():
    """★ `ensure_all` 必须包着那把锁调实现体（第二次进来才会走"已就位"快路径）。"""
    src = inspect.getsource(runtime_assets.ensure_all)
    assert "_ENSURE_ALL_LOCK" in src, "ensure_all 没有套锁"
    assert "_ensure_all_locked" in src, "ensure_all 没有委托给实现体"
    assert hasattr(runtime_assets, "_ensure_all_locked")
    # 实现体本身不该再**取**同一把锁（否则自死锁）。注意判据要精确到 `with` ——
    # 它的 docstring 里会提到这把锁的名字（"调用方必须已持有…"），那不算取锁。
    body = inspect.getsource(runtime_assets._ensure_all_locked)
    assert "with _ENSURE_ALL_LOCK" not in body, "实现体里不许再取同一把锁（会自死锁）"


def test_no_fixed_tmp_name_left():
    """旧的固定临时名写法不许残留（两处都改过）。"""
    src = Path(runtime_assets.__file__).read_text(encoding="utf-8")
    assert "target.name + TMP_SUFFIX)" not in src, "还有地方在用固定临时名"


# --------------------------------------------------------------------------- 时间线
class _Cfg:
    runtime_path = ""

    def __init__(self, root: Path) -> None:
        self.runtime_path = str(root / "runtime")
        self.dlss5_path = str(root / "runtime" / "dlss5")


def _isolate(monkeypatch, root: Path, *, libraries=("X:/a/d3d12.dll", "X:/a/EFMI/d3d11.dll"),
             injections=("d3dcompiler_47.dll", "plugin/poser.dll")) -> _Cfg:
    cfg = _Cfg(root)
    (root / "runtime" / "dlss5").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(injecttrace, "_injection_state",
                        lambda config: {"enabled": True, "extra_libraries": list(libraries),
                                        "signature_len": 12, "config_path": "X:/cfg.json"})
    monkeypatch.setattr(injecttrace, "_dlss5_state",
                        lambda config: {"d3d12.dll": 5592064, "ReShade.ini": 2259,
                                        "dlss5-feed.log": 927, "ReShade.log": 0,
                                        "addons": ["renodx-dlssx.addon64"]})
    from endfieldmodcontroller import game_clean, reshade_integration

    game_dir = root / "game"
    game_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(reshade_integration, "detect_game_dir",
                        lambda config, prefer_actual=False: game_dir)
    monkeypatch.setattr(game_clean, "injection_snapshot", lambda config: set(injections))
    return cfg


def test_snapshot_fields(tmp_path, monkeypatch):
    cfg = _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(injecttrace, "_process_state",
                        lambda pid: {"pid": pid, "alive": True, "module_count": 40,
                                     "third_party_count": 3, "modules": ["d3d12.dll"],
                                     "expect_missing": ["d3d11.dll"]})
    snap = injecttrace.snapshot(cfg, phase="game-started", pid=1234, note="试试")
    assert snap["phase"] == "game-started"
    assert snap["phase_label"] == "终末地启动后"
    assert snap["note"] == "试试"
    assert snap["injection"]["extra_libraries"] == ["X:/a/d3d12.dll", "X:/a/EFMI/d3d11.dll"]
    assert snap["game_injections"], "游戏目录注入物要收到"
    assert snap["dlss5"]["d3d12.dll"] == 5592064
    assert snap["process"]["expect_missing"] == ["d3d11.dll"]


def test_snapshot_never_raises(tmp_path, monkeypatch):
    """取证失败绝不能反噬主流程：每一项都坏掉也要返回一个 dict。"""
    cfg = _Cfg(tmp_path)
    monkeypatch.setattr(injecttrace, "_injection_state",
                        lambda config: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(injecttrace, "_dlss5_state",
                        lambda config: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = injecttrace.snapshot(cfg, phase="crash")
    assert isinstance(snap, dict)
    assert "error" in snap["injection"]
    assert "error" in snap["dlss5"]


def test_record_and_read_roundtrip(tmp_path, monkeypatch):
    cfg = _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(injecttrace, "_process_state", lambda pid: {})
    logs: list[str] = []
    assert injecttrace.record(cfg, phase="launch-begin", log=logs.append)
    assert injecttrace.record(cfg, phase="xxmi-started", log=logs.append)
    entries = injecttrace.read_all(cfg)
    assert [item["phase"] for item in entries] == ["launch-begin", "xxmi-started"]
    assert injecttrace.trace_path(cfg).name == "injection-trace.jsonl"
    assert any("注入时间线[" in line for line in logs), logs


def test_render_shows_phases_and_missing(tmp_path, monkeypatch):
    cfg = _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(injecttrace, "_process_state",
                        lambda pid: {"pid": pid, "alive": True, "module_count": 9,
                                     "third_party_count": 2, "modules": ["d3d12.dll"],
                                     "expect_missing": ["d3d11.dll"]})
    injecttrace.record(cfg, phase="game-started", pid=99)
    text = injecttrace.render(config=cfg)
    assert "终末地启动后" in text
    assert "d3d11.dll" in text and "没进" in text, "「该进进程却没进」必须写出来"
    assert "X:/a/d3d12.dll" in text, "注入库要逐条列出"


def test_render_empty_is_explicit():
    text = injecttrace.render([])
    assert "没有记录" in text


# --------------------------------------------------------------------------- 五个时机
def test_five_phases_are_wired_in_source():
    """★ 五个时机**在源码里真的都接了** —— 少一个，那条时间线就断一节。"""
    launcher_src = inspect.getsource(launcher)
    crashwatch_src = inspect.getsource(crashwatch)
    diagnostics_src = inspect.getsource(diagnostics)
    assert 'phase="launch-begin"' in launcher_src
    assert 'phase="xxmi-started"' in launcher_src
    assert 'phase="game-started"' in crashwatch_src, "共用入口里要有启动后那一张"
    assert 'phase="game-exited"' in crashwatch_src
    assert 'phase="crash"' in crashwatch_src
    # 主路径那个监视器必须真的驱动它们（2026-10-05 修的正是"主路径下从来没跑过"）
    assert "arm_runtime_watch" in diagnostics_src
    assert "poll_runtime_watch" in diagnostics_src
    assert "on_game_exit" in diagnostics_src


def test_on_game_exit_is_shared_by_both_watchers():
    """两个监视器共用同一个退出取证入口（判据只有一处）。"""
    assert "on_game_exit" in inspect.getsource(crashwatch.start_watch)
    assert "_after_game_exit" in inspect.getsource(diagnostics)
    src = inspect.getsource(diagnostics._after_game_exit)
    assert "crashwatch.on_game_exit" in src


def test_phases_constant_matches_labels():
    assert set(injecttrace.PHASES) == set(injecttrace._PHASE_LABEL)
    assert len(injecttrace.PHASES) == 5
