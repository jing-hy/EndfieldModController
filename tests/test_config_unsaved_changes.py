"""「改了内存、中途访问 config 会不会被磁盘冲掉」（2026-10-06）。

**背景**：`api.EndfieldModControllerAPI.config` 这个 property 会在磁盘 mtime 变化时
**整份重新 load 并替换内存对象** —— 目的是让"用户在设置页改了配置"对运行中的进程即时生效。
但若此刻内存里**有还没落盘的改动**，那次 reload 会把改动整份丢掉，随后 `save()` 再把旧值
写回磁盘；用户看到的就是「开关关掉之后过一会又自己打开了」。

**修法**：`AppConfig` 自己记住"有未落盘的改动"（持久化字段被赋值即置位、`save()` 成功即清除），
`api.config` 在该标记为真时**跳过 reload**（此刻磁盘那份必然比内存旧）。

两条都必须成立：
① **有未落盘改动时**：访问 `config` 不能把内存改动冲掉；
② **内存干净时**：仍要能感知"磁盘被外部改了"（这是这个 property 存在的理由，不能弄丢）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from endfieldmodcontroller.config import AppConfig


@pytest.fixture()
def cfg_file(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "data_root": str(tmp_path), "theme": "dark",
        "dlss5_addon_enabled": True, "hotkey_takeover": True,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def _write_cfg(path, **overrides):
    """把配置写到磁盘（模拟"用户在设置页改了配置 / 别的进程动了它"）。

    ⚠️ 必须把 mtime 推后：同一秒内写入时 mtime 可能不变，`property` 就感知不到变化，
    测试会变成"偶发通过"。
    """
    import os
    import time

    data = {"data_root": str(path.parent), "theme": "dark",
            "dlss5_addon_enabled": True, "hotkey_takeover": True}
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + 5))
    time.sleep(0.01)


def _make_api(monkeypatch, cfg_file):
    from endfieldmodcontroller import api as apimod

    cls = next(o for _n, o in vars(apimod).items()
               if hasattr(o, "config") and hasattr(o, "_config_file_mtime"))
    inst = cls.__new__(cls)                       # 跳过 __init__ 的重活
    loaded = AppConfig.load(cfg_file)
    inst._config = loaded
    # ⚠️ 真实实例里 `_config_path` 是 **Path**（`api.py:149` 会把 AppConfig 的 str 转过去，
    #    `_config_file_mtime()` 直接对它 `.stat()`）—— 这里必须照真实类型给。
    inst._config_path = pathlib.Path(cfg_file)
    inst._config_mtime = cfg_file.stat().st_mtime
    return inst, loaded


def test_unsaved_change_survives_a_config_access(monkeypatch, cfg_file):
    """★ 改了内存**还没落盘**时，访问 `config` 不能把改动冲掉。"""
    inst, cfg = _make_api(monkeypatch, cfg_file)

    cfg.dlss5_addon_enabled = False               # 改内存，**故意不 save**
    assert cfg.has_unsaved_changes() is True

    # 让磁盘看起来"变过"（模拟落盘/别的进程动过），再访问 property
    cfg_file.write_text(cfg_file.read_text(encoding="utf-8").replace(
        '"theme": "dark"', '"theme": "light"'), encoding="utf-8")

    got = inst.config
    assert got.dlss5_addon_enabled is False, (
        "★ 未落盘的改动被磁盘内容冲掉了 —— 这正是「开关关掉后又自己打开」的机制"
    )


def test_save_clears_the_flag(monkeypatch, cfg_file):
    """`save()` 成功 ⇒ 标记清除（此后磁盘与内存一致，可以正常感知外部改动）。"""
    _inst, cfg = _make_api(monkeypatch, cfg_file)
    cfg.theme = "amber"
    assert cfg.has_unsaved_changes() is True
    cfg.save()
    assert cfg.has_unsaved_changes() is False
    on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert on_disk["theme"] == "amber"


def test_external_change_still_reloads_when_memory_is_clean(monkeypatch, cfg_file):
    """★ 内存干净时，**仍要**能感知磁盘被外部改动（这个 property 的存在理由）。"""
    inst, cfg = _make_api(monkeypatch, cfg_file)
    assert cfg.has_unsaved_changes() is False

    cfg_file.write_text(json.dumps({
        "data_root": str(cfg_file.parent), "theme": "cyan",
        "dlss5_addon_enabled": True, "hotkey_takeover": True,
    }, ensure_ascii=False), encoding="utf-8")
    # 确保 mtime 与缓存不同（同一秒内写入时 mtime 可能一样）
    import os
    import time
    stat = cfg_file.stat()
    os.utime(cfg_file, (stat.st_atime, stat.st_mtime + 5))
    time.sleep(0.01)

    got = inst.config
    assert got.theme == "cyan", "内存干净时应当重新加载磁盘上的新配置"


def test_runtime_only_attrs_do_not_dirty(monkeypatch, cfg_file):
    """下划线开头的是运行期缓存，不该把配置标成"有未落盘改动"。"""
    _inst, cfg = _make_api(monkeypatch, cfg_file)
    cfg.save()                                    # 先清干净
    assert cfg.has_unsaved_changes() is False
    cfg._relocated = ["x"]                        # noqa: SLF001 - 就是要测这个
    assert cfg.has_unsaved_changes() is False


def test_load_finishes_clean(cfg_file):
    """★★ **`load()` 结束后标记必须是干净的**（2026-10-06 实测暴露的副作用）。

    `load()` 内部的迁移/补齐会赋值、从而把标记置为 True —— 可那**不是用户的改动**。
    若不清掉，脏保护会**永久生效** ⇒「用户在设置页改配置、运行中的进程即时生效」
    这个能力就丢了（那正是 `api.config` 那个 property 存在的理由）。
    """
    cfg = AppConfig.load(cfg_file)
    assert cfg.has_unsaved_changes() is False, (
        "load() 结束时仍是脏的 ⇒ 之后 property 永远不再重载 ⇒ 外部改配置不再生效"
    )


def test_external_change_works_after_a_reload(monkeypatch, cfg_file):
    """★ 端到端守住上面那条：**发生过一次重载之后**，外部改动仍要被感知到。"""
    inst, cfg = _make_api(monkeypatch, cfg_file)
    assert cfg.has_unsaved_changes() is False

    # 第一次外部改动 ⇒ 触发重载
    _write_cfg(cfg_file, theme="amber")
    assert inst.config.theme == "amber"
    assert inst.config.has_unsaved_changes() is False, "重载之后不该留着脏标记"

    # 第二次外部改动 ⇒ 仍要能被感知（若第一次留下脏标记，这里就会失败）
    _write_cfg(cfg_file, theme="violet")
    assert inst.config.theme == "violet", "第一次重载留下的脏标记把后续重载全挡掉了"
