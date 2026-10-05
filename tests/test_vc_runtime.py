"""「VC++ 运行库」自检项的回归测试（2026-10-05，方案 3）。

为什么有这一项：issue #16 反馈者现场的游戏退出码是 `0xC0000135`
（STATUS_DLL_NOT_FOUND），而注入链上唯一依赖 VC++ 运行库的组件是
`dlss5-feed.addon64`（MSVCP140 / VCRUNTIME140）；他机器上是 14.42.34438、
开发机是 14.51.36247。

要守住的性质：
* **版本比较按数字逐段来**（不能按字符串比 —— 字符串比会把 `14.5` 判成比 `14.42` 新）；
  段数不同（`14.40` 与 `14.40.0`）也要能比；
* **缺文件才是故障**（manual + 官方下载地址）；**在位只报版本号**（不判"旧" ——
  没有可靠阈值就不编阈值，把事实摆出来给两台机器对照）；
* **版本读不到**不许当成"故障"（读不到 ≠ 没有）；
* 报出来的消息里**必须带版本号**（这条判据的价值就在于能对照）。

全部离线：`_vc_runtime_versions()` 打桩，**不碰真实 System32**。
"""
from __future__ import annotations

from endfieldmodcontroller import initialize


class _Recorder:
    """假的 Report：只记下 `add()` 的调用。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, key, ok, message, *, fixed=False, manual=False) -> None:  # noqa: ANN001
        self.items.append({"key": key, "ok": ok, "message": message,
                           "fixed": fixed, "manual": manual})


def _found(msvcp="", vcruntime="", vcruntime1="", *, missing=()) -> dict:
    def entry(name, version):
        return {"path": f"C:\\Windows\\System32\\{name}",
                "version": version, "missing": name in missing}
    return {
        "msvcp140.dll": entry("msvcp140.dll", msvcp),
        "vcruntime140.dll": entry("vcruntime140.dll", vcruntime),
        "vcruntime140_1.dll": entry("vcruntime140_1.dll", vcruntime1),
    }


def _all(version: str, *, missing=()) -> dict:
    return _found(msvcp=version, vcruntime=version, vcruntime1=version, missing=missing)


def _check(monkeypatch, found) -> _Recorder:
    monkeypatch.setattr(initialize, "_vc_runtime_versions", lambda: found)
    rec = _Recorder()
    initialize._check_vc_runtime(None, rec, None)  # type: ignore[arg-type]
    return rec


# --------------------------------------------------------------- 版本比较
def test_version_tuple_orders_numerically():
    """按**数字**逐段比：`14.42` 比 `14.5` 新（按字符串比会反过来 —— 这正是要防的坑）。"""
    assert initialize._version_tuple("14.42.34438.0") > initialize._version_tuple("14.5.0")
    assert initialize._version_tuple("14.40") == (14, 40)
    assert initialize._version_tuple("") == ()


def test_outdated_compares_full_versions():
    """低于下限 ⇒ True；等于/高于 ⇒ False；段数不同也能比。"""
    assert initialize.vc_runtime_outdated(_all("14.38.33130.0")) is True
    assert initialize.vc_runtime_outdated(_all("14.42.34438.0")) is False
    assert initialize.vc_runtime_outdated(_all("14.40.0")) is False
    assert initialize.vc_runtime_outdated(_found(msvcp="14.39.0")) is True


def test_outdated_ignores_unreadable_versions():
    """版本读不到 ⇒ 不判"旧"（读不到 ≠ 没有，免得误报）。"""
    assert initialize.vc_runtime_outdated(_found()) is False


# --------------------------------------------------------------- 自检三态
def test_missing_is_reported_as_failure(monkeypatch):
    rec = _check(monkeypatch, _all("14.51.36247.0", missing=("vcruntime140_1.dll",)))
    item = rec.items[0]
    assert item["key"] == "vc_runtime" and item["ok"] is False and item["manual"] is True
    assert "vcruntime140_1.dll" in item["message"]
    assert initialize.VC_RUNTIME_URL in item["message"], "缺了就要给出官方下载地址"


def test_old_but_present_is_a_hint_with_url(monkeypatch):
    """低于下限：**不当故障**报（ok=True），但消息里带版本号与官方入口。"""
    rec = _check(monkeypatch, _all("14.38.33130.0"))
    item = rec.items[0]
    assert item["ok"] is True and item["manual"] is False
    assert "14.38.33130.0" in item["message"]
    assert initialize.VC_RUNTIME_URL in item["message"]


def test_reporter_version_also_reports_numbers_and_url(monkeypatch):
    """反馈者那台（14.42）走"在位"分支：不报故障，但**版本号与更新入口都要有** ——
    这正是这一项存在的意义（两台机器一眼对照）。"""
    rec = _check(monkeypatch, _all("14.42.34438.0"))
    item = rec.items[0]
    assert item["ok"] is True and item["manual"] is False
    assert "14.42.34438.0" in item["message"]
    assert initialize.VC_RUNTIME_URL in item["message"]


def test_current_versions_pass(monkeypatch):
    rec = _check(monkeypatch, _all("14.51.36247.0"))
    item = rec.items[0]
    assert item["ok"] is True and item["manual"] is False
    assert "14.51.36247.0" in item["message"]


def test_unreadable_versions_do_not_claim_failure(monkeypatch):
    """三个文件都在、但版本读不出来 ⇒ 仍然报 ok（只说"版本读不到"）。"""
    rec = _check(monkeypatch, _found())
    item = rec.items[0]
    assert item["ok"] is True
    assert "版本读不到" in item["message"]


def test_summary_lists_missing_and_present(monkeypatch):
    summary = initialize.vc_runtime_summary(_all("14.42.34438.0", missing=("msvcp140.dll",)))
    assert "msvcp140.dll" in summary and "14.42.34438.0" in summary


# --------------------------------------------------------------- 接进"依赖安装"（2026-10-05）
def test_builtin_report_has_vc_entry(monkeypatch, tmp_path):
    """依赖页列表里要有这一行（带版本号），并标成**系统组件** —— 前端据此换装法。"""
    from endfieldmodcontroller import runtime_deps
    from endfieldmodcontroller.config import AppConfig

    monkeypatch.setattr(initialize, "_vc_runtime_versions", lambda: _all("14.51.36247.0"))
    config = AppConfig(
        runtime_dir=str(tmp_path / "runtime"),
        builtin_runtime_dir=str(tmp_path / "runtime" / "builtin"),
        library_dir=str(tmp_path / "library"),
    )
    entry = runtime_deps.builtin_report(config).get("VC++ 运行库")
    assert entry, "依赖页少了 VC++ 运行库这一行"
    assert entry["system_component"] is True
    assert entry["status"] == "已安装" and "14.51.36247.0" in entry["version"]


def test_vc_runtime_result_states(monkeypatch):
    """缺 ⇒ `needs_install`（前端据此弹「安装/跳过」）；在位 ⇒ `present`（不打扰）。"""
    from endfieldmodcontroller import runtime_deps

    monkeypatch.setattr(initialize, "_vc_runtime_versions",
                        lambda: _all("14.51.0", missing=("msvcp140.dll",)))
    missing_result = runtime_deps.vc_runtime_result()
    assert missing_result.status == "needs_install"
    assert "msvcp140.dll" in missing_result.message

    monkeypatch.setattr(initialize, "_vc_runtime_versions", lambda: _all("14.51.0"))
    assert runtime_deps.vc_runtime_result().status == "present"


def test_ensure_all_treats_needs_install_as_ok_and_appends_vc():
    """钉住两件事（都是"忘了就静默失效"的那种）：

    ① `needs_install` 必须在 `ok_status` 里 —— 否则它会被当成失败项**重试 3 次**；
    ② `ensure_all` 结束前要把这条检查**追加进结果** —— 否则前端永远看不到、也就不会弹窗。
    """
    import inspect

    from endfieldmodcontroller import runtime_deps

    src = inspect.getsource(runtime_deps.ensure_all)
    assert "needs_install" in src, "needs_install 没进 ok_status ⇒ 会被当失败重试 3 次"
    assert "vc_runtime_result()" in src, "ensure_all 没把 VC 检查追加进结果"
