"""Mod 库要**抢在界面就绪之前**扫完，而且只扫一次（2026-10-07 用户实测反馈）。

用户原话：「**打开管理器后，Mod 库列表要等一会才显示出来**」。

原因链：`get_state()` 里 `_mods()` 是**首次调用时同步扫库**，而在此之前界面已经起来、
Mod 库页是空的；扫描本身不慢（本机 13 GB / 36 个 Mod 约 0.25 秒，大盘库是秒级），
但它**串在首屏那条路上**。

修法两层：
* `_warm_up()` 里**先扫一次再等 `ui_ready`** —— 这一段与"创建窗口 + WebView2 加载前端"
  并行，首屏那次 `get_state()` 进来时缓存已好；
* `_mods()` 加锁双检 —— 预热线程与首屏同时想要结果时，后来者等先来的那次，
  **不许各扫一遍**（否则首屏那遍等于白等）。
"""
from __future__ import annotations

import ast
import inspect
import threading
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from endfieldmodcontroller import api as api_module


def test_prewarm_scan_happens_before_waiting_for_ui():
    """★ 顺序判据：`_warm_up` 里扫库必须排在 `_ui_ready.wait()` **之前**。

    顺序反了（先等 ui_ready 再扫）就等于"界面起来之后才开始扫"，首屏照样要等它。
    """
    # ⚠️ 这是个**方法**（源码带 4 空格缩进）⇒ 必须先 dedent 再 parse，
    #    否则 `ast.parse` 直接抛 IndentationError（模块级函数才不用管这一步）。
    src = textwrap.dedent(inspect.getsource(api_module.EndfieldModControllerApi._warm_up))
    tree = ast.parse(src)
    scan_lines: list[int] = []
    wait_lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if getattr(func, "attr", None) == "_mods":
                scan_lines.append(node.lineno)
            if getattr(func, "attr", None) == "wait":
                wait_lines.append(node.lineno)
    assert scan_lines, "★ _warm_up 里没有预热 Mod 库 ⇒ 首屏还要等扫描"
    assert wait_lines, "_warm_up 里没找到 ui_ready.wait"
    assert min(scan_lines) < min(wait_lines), (
        "★ 预热被排在 ui_ready.wait() 之后 ⇒ 它要等界面就绪才开始，首屏照样卡"
    )


def _bare_api(tmp_path, monkeypatch, calls: list[int], delay: float = 0.05):
    """绕开 `__init__`（它会起预热线程、拉公告）造一个只带 `_mods` 需要的属性的实例。"""
    api = api_module.EndfieldModControllerApi.__new__(api_module.EndfieldModControllerApi)
    api._mods_cache = None
    api._mods_lock = threading.Lock()
    api._mods_gen = 0
    api.config = SimpleNamespace(library_path=tmp_path / "library",
                                 staging_mods_path=tmp_path / "Mods")

    def fake_scan(_library, _staging):
        calls.append(1)
        time.sleep(delay)          # 把"正在扫"的窗口拉长，逼出并发问题
        return ["mod-a", "mod-b"]

    monkeypatch.setattr(api_module.core, "scan_library", fake_scan)
    return api


def test_concurrent_callers_scan_only_once(tmp_path, monkeypatch):
    """★ 预热与首屏同时要 ⇒ **只扫一次**（四路并发也只许扫一次）。"""
    calls: list[int] = []
    api = _bare_api(tmp_path, monkeypatch, calls)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: api._mods(), range(4)))

    assert len(calls) == 1, f"★ 扫了 {len(calls)} 次（应该是 1 次）—— 首屏那遍等于白等"
    assert all(r == ["mod-a", "mod-b"] for r in results)


def test_repeated_calls_use_the_cache(tmp_path, monkeypatch):
    calls: list[int] = []
    api = _bare_api(tmp_path, monkeypatch, calls)
    first = api._mods()
    second = api._mods()
    assert first is second and len(calls) == 1


def test_invalidate_forces_a_rescan(tmp_path, monkeypatch):
    """对照：`_invalidate_mods()`（重新扫描 / 导入 Mod 之后调）必须真的让下次重扫。"""
    calls: list[int] = []
    api = _bare_api(tmp_path, monkeypatch, calls)
    api._mods()
    api._invalidate_mods()
    api._mods()
    assert len(calls) == 2


def test_scan_started_before_invalidate_is_discarded(tmp_path, monkeypatch):
    """★★ **竞态判据**：预热正在扫的时候有人 invalidate ⇒ 那次结果必须作废、重扫。

    不这么做的话：预热扫出来的是"加 Mod 之前"的列表，它会在 invalidate 之后写回缓存，
    用户看到的就是加完 Mod 列表还是旧的（`tests/test_mod_backup.py` 就是这么抓到它的：
    备份数量少了一个）。
    """
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def slow_scan(_library, _staging):
        calls.append(1)
        started.set()
        release.wait(timeout=5)        # 扫描"卡"在这里，等主线程去 invalidate
        return ["旧列表"]

    api = _bare_api(tmp_path, monkeypatch, calls, delay=0)
    monkeypatch.setattr(api_module.core, "scan_library", slow_scan)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api._mods)
        assert started.wait(timeout=5)
        api._invalidate_mods()         # 扫描期间库变了
        release.set()
        future.result(timeout=5)

    assert len(calls) >= 2, "★ 扫描期间被 invalidate，却没重扫 ⇒ 过期结果会被写进缓存"
    assert api._mods() == ["旧列表"]


def test_renaming_a_mod_waits_for_a_running_scan(tmp_path, monkeypatch):
    """★★ **互斥判据**：改库（改名）必须等正在进行的扫描，不许并行。

    为什么（2026-10-07，构建连挂三轮）：预热会在"界面就绪之前"扫库，扫描会**打开每个
    Mod 的文件**；而 Windows 上"文件正被读"时重命名/删除目录会偶发失败 ——
    表现就是构建时每轮挂在一个不同的用例上（`rename_mod` 返回 False、文件没生成）。
    这里直接把锁摁住模拟"扫描进行中"，验证改名**等在锁上**。
    """
    library = tmp_path / "library"
    mod_dir = library / "old"
    mod_dir.mkdir(parents=True)
    (mod_dir / "mod.meta.json").write_text('{"name": "old", "id": "m1"}', encoding="utf-8")

    api = api_module.EndfieldModControllerApi.__new__(api_module.EndfieldModControllerApi)
    api._mods_lock = threading.RLock()
    api._mods_gen = 0
    api._mods_cache = ["fake"]
    api.config = SimpleNamespace(library_path=library, save=lambda: None)
    mod = SimpleNamespace(id="m1", name="old", path=str(mod_dir))
    api._mods = lambda: [mod]                       # 绕开真实扫描
    api._library_top_dir = lambda _mod: mod_dir
    api._invalidate_mods = lambda: None
    monkeypatch.setattr(api_module.launcher, "_append_log", lambda *a, **k: None)

    # 模拟"后台扫描持锁"
    api._mods_lock.acquire()
    done = threading.Event()

    def do_rename():
        api.rename_mod("m1", "new")
        done.set()

    worker = threading.Thread(target=do_rename, daemon=True)
    worker.start()
    try:
        # 锁还被"扫描"占着 ⇒ 改名必须卡住，目录名不能已经变了
        assert not done.wait(timeout=0.4), "★ 改名没等扫描结束就动了库目录"
        assert mod_dir.is_dir() and not (library / "new").exists()
    finally:
        api._mods_lock.release()
    assert done.wait(timeout=5), "锁放开后改名仍未完成"
    worker.join(timeout=5)
    assert (library / "new").is_dir(), "改名最终应当成功"
