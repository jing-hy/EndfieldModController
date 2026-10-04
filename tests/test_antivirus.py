"""杀毒线（`antivirus`）的离线测试（2026-10-04）。

用户原话：「杀毒有没有办法处理，或者检测加弹窗」+「3 默认开，在设置留个开关」。

这里**不跑真的 PowerShell**（慢、依赖机器状态），只钉住三件容易出错的事：

1. **筛选**：Defender 的处置记录里，只有**路径落在我们目录下**的那些才该打扰用户 ——
   别人机器上被隔离的乱七八糟的东西跟我们无关；
2. **"查不到" ≠ "没有"**：命令失败必须把原因带回，不能伪装成"没有记录"
   （拿不到证据时要说拿不到，这是这个项目的既定准则）；
3. **做不到就如实说做不到**：非管理员 / 没有目标目录时，不许返回"成功"。
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from endfieldmodcontroller import antivirus


# ── 筛选 ──────────────────────────────────────────────────────────────────────

def test_detections_keep_only_our_paths() -> None:
    """★ 只有落在我们目录下的隔离记录才算 —— 其它的一律不打扰用户。"""
    out = "\n".join([
        r"2026-10-04T12:00:00|2147720000|C:\Users\x\Downloads\runtime\dlss5\nvngx_dlssnr.dll",
        r"2026-10-04T11:00:00|2147720000|E:\Hypergryph Launcher\games\Arknights Endfield\d3dcompiler_47.dll",
        r"2026-10-04T10:00:00|2147720000|D:\别的软件\random.exe",
    ])
    roots = [Path(r"C:\Users\x\Downloads"),
             Path(r"E:\Hypergryph Launcher\games\Arknights Endfield")]
    with mock.patch.object(antivirus, "_powershell", return_value=(out, "")):
        hits, err = antivirus.recent_detections(roots)
    assert err == ""
    assert len(hits) == 2, hits
    files = [f for hit in hits for f in hit["files"]]
    assert any("nvngx_dlssnr.dll" in f for f in files)
    assert any("d3dcompiler_47.dll" in f for f in files)
    assert not any("random.exe" in f for f in files), "无关的隔离记录不该出现在提醒里"


def test_detection_with_multiple_resources_per_entry() -> None:
    """一条记录里可能有多个资源路径（`Resources` 是数组，我们用 `;` 拼回来的）。"""
    out = (r"2026-10-04T12:00:00|2147720000|"
           r"C:\data\runtime\dlss5\a.addon64;D:\other\b.exe")
    with mock.patch.object(antivirus, "_powershell", return_value=(out, "")):
        hits, _err = antivirus.recent_detections([Path(r"C:\data")])
    assert len(hits) == 1
    assert hits[0]["files"] == [r"C:\data\runtime\dlss5\a.addon64"], "只留落在我们目录下的那个"


def test_query_failure_is_reported_not_swallowed() -> None:
    """★ 「查不到」必须与「没有记录」分开 —— 否则会得出相反结论。"""
    with mock.patch.object(antivirus, "_powershell", return_value=("", "Access is denied")):
        hits, err = antivirus.recent_detections([Path(r"C:\x")])
    assert hits == []
    assert err, "命令失败要把原因带回，不能伪装成'没有隔离记录'"


# ── 降级路径 ──────────────────────────────────────────────────────────────────

def test_apply_without_targets_says_so() -> None:
    """没有需要加白的目录（数据根/游戏目录都没定位到）⇒ 如实说明，不算成功。"""
    with mock.patch.object(antivirus, "targets", return_value=[]):
        result = antivirus.apply_exclusions(object())
    assert result["ok"] is False
    assert "没有" in result["message"]


def test_apply_requires_admin() -> None:
    """★ 非管理员时不许假装加成功 —— 返回的是"当前身份做不了"，由上层降级成提示。"""
    with mock.patch.object(antivirus, "targets", return_value=[Path(r"C:\x")]), \
         mock.patch.object(antivirus, "is_admin", return_value=False):
        result = antivirus.apply_exclusions(object())
    assert result["added"] == []
    assert result["ok"] is False
    assert "管理员" in result["message"]


def test_apply_skips_paths_already_excluded() -> None:
    """★ 幂等：已经在白名单里的目录**不再重复写**（这是"默认开"能安心自动跑的前提）。"""
    target = r"C:\Users\x\Downloads"
    with mock.patch.object(antivirus, "targets", return_value=[Path(target)]), \
         mock.patch.object(antivirus, "is_admin", return_value=True), \
         mock.patch.object(antivirus, "current_exclusions",
                           return_value=([target], "")), \
         mock.patch.object(antivirus, "_powershell") as ps:
        result = antivirus.apply_exclusions(object())
    assert result["added"] == []
    assert result["skipped"] == [target]
    ps.assert_not_called()   # 已经在白名单里就不该再去调 Add-MpPreference


def test_apply_reports_each_failure() -> None:
    """单条失败要**逐条**报出来，不能让"加了两条成功一条失败"看起来像"全成"。"""
    with mock.patch.object(antivirus, "targets",
                           return_value=[Path(r"C:\a"), Path(r"C:\b")]), \
         mock.patch.object(antivirus, "is_admin", return_value=True), \
         mock.patch.object(antivirus, "current_exclusions", return_value=([], "")), \
         mock.patch.object(antivirus, "_powershell",
                           side_effect=[("", ""), ("", "拒绝访问")]):
        result = antivirus.apply_exclusions(object())
    assert result["added"] == [r"C:\a"]
    assert len(result["failed"]) == 1 and "拒绝访问" in result["failed"][0]
    assert result["ok"] is False, "有失败就不能报 ok"


# ── 缓存 ──────────────────────────────────────────────────────────────────────

def test_cache_roundtrip() -> None:
    """`cached()` 在没算过时是 None；`reset_cache()` 之后又回到 None。"""
    antivirus.reset_cache()
    assert antivirus.cached() is None
    with mock.patch.object(antivirus, "status", return_value={
            "supported": True, "admin": True, "wanted": [], "exclusions": [],
            "missing": [], "note": ""}), \
         mock.patch.object(antivirus, "recent_detections", return_value=([], "")):
        snap = antivirus.scan_once(object())
    assert antivirus.cached() is snap
    assert snap["detections"] == []
    antivirus.reset_cache()
    assert antivirus.cached() is None
