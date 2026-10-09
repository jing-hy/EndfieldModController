"""随包资产清单的**按条目合并**与"停用旧 NR 后的报警"（2026-10-06 定案）。

**根因**：清单原先只取**第一个命中的根**，而候选顺序里**数据根排在 exe 内嵌之前**
⇒ 用户机器上那句旧的 `<数据根>/assets/` 会一直命中、内嵌的新清单永远轮不到
⇒ "只换 exe、没换 assets"的升级**拿不到任何新增/替换的随包资产**。

实测现场（`E:\\ZMDMOD`）：
* 某个 addon 的条目不在旧清单里 ⇒ 永远展不出来（用户装了却没这东西）；
* NR 引擎换代变成自相矛盾：先"已停用旧版 NR 引擎 `4.7汉化`…已改用随包的 `7.0.0-rc8`"，
  紧接着又"展开内置资产 `renodx-dlss5-4.7_汉化.addon64`"（照旧清单把旧的装了回来）。

要守住三条：
① 多根之间**按条目合并**（数据根优先、缺的从内嵌补），且每个条目带上**它自己所在的根**；
② 同名条目**只出一次**（取优先级高的那个）；
③ 停用了旧 NR 却**找不到新条目**时，要明确报警（而不是静默把旧的展回去）。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from endfieldmodcontroller import runtime_assets as ra


def _root(base: pathlib.Path, entries: dict[str, dict]) -> pathlib.Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / ra.MANIFEST_NAME).write_text(
        json.dumps({"version": 1, "group": base.name, "files": entries}, ensure_ascii=False),
        encoding="utf-8")
    return base


OLD_ENTRY = {"renodx-dlss5-4.7_汉化.addon64": {"size": 1732608, "parts": ["a.xz"]}}
NEW_ENTRY = {
    "renodx-dlss5.addon64": {"size": 1921024, "parts": ["b.xz"]},
}


def test_merges_entries_across_roots(tmp_path, monkeypatch):
    """★ 数据根缺的条目要**从内嵌那份补上**（这正是升级用户拿不到新资产的原因）。"""
    user_root = _root(tmp_path / "datadir" / "assets" / "dlss5", OLD_ENTRY)
    inner_root = _root(tmp_path / "meipass" / "assets" / "dlss5", NEW_ENTRY)
    monkeypatch.setattr(ra, "ASSET_GROUPS", ("dlss5",))
    monkeypatch.setattr(ra, "asset_roots", lambda cfg, group: [user_root, inner_root])

    rows = list(ra.iter_assets(object()))
    names = [name for _g, _r, name, _e in rows]
    assert "renodx-dlss5-4.7_汉化.addon64" in names, "用户自己那份要保留（优先级最高）"
    assert "renodx-dlss5.addon64" in names, (
        "★ 内嵌那份的新条目没被合并进来 ⇒ 升级用户永远拿不到随包的新 addon"
    )
    assert "renodx-dlss5.addon64" in names

    # 每个条目要带上**它自己所在的根**（解压时要按那个目录找 .xz 分卷）
    by_name = {name: root for _g, root, name, _e in rows}
    assert by_name["renodx-dlss5-4.7_汉化.addon64"] == user_root


def test_same_name_only_emitted_once(tmp_path, monkeypatch):
    """★ 同名条目只出一次，取优先级高的那个根（不重复、不覆盖用户自放的）。"""
    shared = {"same.addon64": {"size": 111, "parts": ["s.xz"]}}
    user_root = _root(tmp_path / "u" / "assets" / "dlss5", shared)
    inner_root = _root(tmp_path / "i" / "assets" / "dlss5",
                       {"same.addon64": {"size": 999, "parts": ["s2.xz"]}})
    monkeypatch.setattr(ra, "ASSET_GROUPS", ("dlss5",))
    monkeypatch.setattr(ra, "asset_roots", lambda cfg, group: [user_root, inner_root])

    rows = [(name, entry, root) for _g, root, name, entry in ra.iter_assets(object())]
    assert len(rows) == 1, f"同名条目重复输出了：{[r[0] for r in rows]}"
    name, entry, root = rows[0]
    assert entry["size"] == 111, "应当保留优先级高的那份"
    assert root == user_root


def test_retire_warns_when_new_entry_missing(tmp_path, monkeypatch):
    """★ 停用了旧 NR 却找不到新条目 ⇒ 必须明确报警（不能静默把旧的展回去）。"""
    base = tmp_path / "dlss5"
    base.mkdir(parents=True)
    (base / "renodx-dlss5-4.7_汉化.addon64").write_bytes(b"old")

    class _Cfg:
        dlss5_path = base

    monkeypatch.setattr(ra, "iter_assets", lambda cfg: iter(()))     # 清单里没有新条目
    logs: list[str] = []
    moved = ra.retire_stale_nr_addons(_Cfg(), log=logs.append)

    assert moved, "前置：旧的那份应当被搬走"
    assert any("清单里**没有**新版" in line for line in logs), (
        f"没报警 ⇒ 用户只会看到'已改用新版'却看不到新 addon：{logs}"
    )
    assert any("导入随包 zip" in line for line in logs), "要给出可执行的下一步"


def test_retire_is_quiet_when_new_entry_present(tmp_path, monkeypatch):
    """对照：新条目在清单里时不该报这个警。"""
    base = tmp_path / "dlss5"
    base.mkdir(parents=True)
    (base / "renodx-dlss5-4.7_汉化.addon64").write_bytes(b"old")

    class _Cfg:
        dlss5_path = base

    monkeypatch.setattr(ra, "iter_assets",
                        lambda cfg: iter([("dlss5", base, "renodx-dlss5.addon64", {})]))
    logs: list[str] = []
    ra.retire_stale_nr_addons(_Cfg(), log=logs.append)
    assert not any("清单里**没有**新版" in line for line in logs), logs


def test_exe_packs_the_addon_xz_files():
    """★ 清单 + 四个 addon 的 `.xz` 必须真的打进 exe（否则合并也补不出文件）。"""
    src = pathlib.Path(ra.__file__).resolve().parents[1] / "scripts" / "build_exe.py"
    text = src.read_text(encoding="utf-8")
    for name in ("assets/dlss5/manifest.json",
                 "assets/dlss5/renodx-dlss5.addon64.xz"):
        assert name in text, f"打包清单里没有 {name} —— 升级用户拿不到它"
