"""机器侧稳定性取证（`kernel_instability`）—— 2026-10-07 新增判据。

**为什么值得一批单测**：这段代码的价值全在「**如实**」两个字上 ——
解析漏条、"没有事件"被当成"采集失败"、或"没查到"被渲染成"机器是稳的"，
任何一条都会把归因带偏（2026-10-07 那份外部反馈档案就是这么偏的：它把**两个
不同异常码**的崩溃合成了一件事，再用后者的现场去证明前者的成因）。

**全部离线**：不跑 PowerShell、不碰真实事件日志（`_run_powershell` 一律打桩）。

⚠️ 样本里的 `Epoch` 一律**用 `_epoch()` 现算**，不写死数字 —— 时间语义必须与解析端
同一套（写死的话，跑到别的时区的机器上就会红，而这种红是假警报）。
"""
from __future__ import annotations

import time
import types

import pytest

from endfieldmodcontroller import kernel_instability


def _epoch(text: str) -> int:
    """把"本地时间文本"换算成 epoch（与 PowerShell 端的 `LocalDateTime` 同一语义）。"""
    return int(time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S")))


_T1, _T2, _T3 = "2026-10-07 12:22:08", "2026-10-07 12:31:02", "2026-10-07 17:42:25"

# 一份**真实形状**的 `Format-List` 输出：两条查询用分隔行隔开，
# `Message` 里带空行与缩进续行（真实事件正文就是这样）。
_SAMPLE = f"""At               : {_T1}
Epoch            : {_epoch(_T1)}
Id               : 41
ProviderName     : Microsoft-Windows-Kernel-Power
Message          : 系统已在未先正常关机的情况下重新启动。如果系统停止响应、发生崩溃或意外断电，则可能会导致此错误。

At               : {_T2}
Epoch            : {_epoch(_T2)}
Id               : 1001
ProviderName     : Microsoft-Windows-WER-SystemErrorReporting
Message          : 计算机已从 Bug 检查中重启。Bug 检查: 0x00000116。转储已保存。

  详情续行：缩进的行应当并回上一个字段
MC-ERR1:
{kernel_instability._SPLIT}
At               : {_T3}
Epoch            : {_epoch(_T3)}
Id               : 1074
ProviderName     : User32
Message          : 进程 C:\\Windows\\system32\\svchost.exe (DESKTOP-ABC) 启动了计算机的 重启

MC-ERR2:
"""


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """每条用例都从"没采过"开始 —— 否则缓存会把打桩结果串到后面的用例。"""
    monkeypatch.setattr(kernel_instability, "_CACHE", None)


# ---------------------------------------------------------------------------
# 解析：这段最容易被"想当然的写法"毁掉
# ---------------------------------------------------------------------------
def test_parse_records_keeps_every_record():
    """**不能按空行切块** —— `Message` 正文自带空行，那样切会把多条并成一条。

    实测：退化成按空行切块的写法时，6 条记录只解析出 1 条（静默丢 5 条）。
    """
    records = kernel_instability._parse_records(_SAMPLE)
    assert len(records) == 3
    assert [item["Id"] for item in records] == ["41", "1001", "1074"]


def test_parse_records_joins_indented_continuation():
    records = kernel_instability._parse_records(_SAMPLE)
    assert "详情续行" in records[1]["Message"]


def test_parse_records_ignores_blank_lines():
    assert kernel_instability._parse_records("\n\n  \n") == []


# ---------------------------------------------------------------------------
# 分类与关键信息
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("event_id,provider,expected", [
    (41, "Microsoft-Windows-Kernel-Power", "unexpected_shutdown"),
    (6008, "EventLog", "unexpected_shutdown"),
    (1001, "Microsoft-Windows-WER-SystemErrorReporting", "bugcheck"),
    (1074, "User32", "shutdown_initiator"),
    (17, "Microsoft-Windows-WHEA-Logger", "whea"),
    (9999, "SomethingElse", "other"),
])
def test_classify(event_id, provider, expected):
    assert kernel_instability._classify(event_id, provider) == expected


def test_bugcheck_detail_normalizes_code():
    detail = kernel_instability._detail("bugcheck", "Bug 检查: 0x00000116 (0xff…)")
    assert detail == "0x00000116"


def test_shutdown_initiator_detail_names_process():
    detail = kernel_instability._detail(
        "shutdown_initiator", r"进程 C:\Windows\system32\svchost.exe 启动了计算机的重启")
    assert "svchost.exe" in detail
    assert "重启" in detail


# ---------------------------------------------------------------------------
# 整段解析：两块查询、时间升序、错误分离
# ---------------------------------------------------------------------------
def test_parse_output_reads_both_blocks_in_time_order():
    data = kernel_instability._parse_output(_SAMPLE, 30, 123.0)
    assert data["ok"] is True
    assert [event["at_text"] for event in data["events"]] == [_T1, _T2, _T3]
    assert data["counts"] == {
        "unexpected_shutdown": 1, "bugcheck": 1, "shutdown_initiator": 1}
    assert data["bugchecks"] == {"0x00000116": 1}
    assert data["error"] == ""


def test_event_carries_both_epoch_and_local_text():
    """`Epoch` 与 `At` 必须来自同一时刻 —— 只取一个就够，但取错字段会静默错一整个时区。"""
    event = kernel_instability._parse_output(_SAMPLE, 30, 1.0)["events"][0]
    assert event["at"] == _epoch(_T1)
    assert event["at_text"] == _T1


@pytest.mark.parametrize("message", [
    "Get-WinEvent: 找不到任何与指定的选择条件匹配的事件。",   # 实测本机（中文）文案
    "Get-WinEvent: 没有找到符合指定选择条件的事件。",
    "No events were found that match the specified selection criteria.",
])
def test_no_events_message_is_not_a_failure(message):
    """「没有符合条件的事件」是**正常结果**（窗口内就是没有蓝屏），不是采集失败。

    实测踩到：原来的提示词只覆盖「没有找到符合…」，而本机文案是
    「找不到任何与指定的选择条件匹配的事件。」⇒ 报告里多了一条假的"采集有错误"。
    """
    text = f"MC-ERR1:{message}\n{kernel_instability._SPLIT}\nMC-ERR2:\n"
    data = kernel_instability._parse_output(text, 30, 1.0)
    assert data["ok"] is True
    assert data["error"] == ""
    assert data["events"] == []


def test_real_error_is_kept():
    text = ("MC-ERR1:Get-WinEvent: 日志名称无效或未安装\n"
            f"{kernel_instability._SPLIT}\nMC-ERR2:\n")
    data = kernel_instability._parse_output(text, 30, 1.0)
    assert "日志名称无效" in data["error"]


def test_no_events_and_real_error_in_the_same_line_keeps_the_real_one():
    text = ("MC-ERR1:Get-WinEvent: 找不到任何与指定的选择条件匹配的事件。 | "
            "访问被拒绝\n"
            f"{kernel_instability._SPLIT}\nMC-ERR2:\n")
    data = kernel_instability._parse_output(text, 30, 1.0)
    assert "访问被拒绝" in data["error"]


# ---------------------------------------------------------------------------
# 采集：失败如实、缓存不重复跑
# ---------------------------------------------------------------------------
def test_collect_reports_failure_instead_of_pretending_empty(monkeypatch):
    monkeypatch.setattr(kernel_instability, "_run_powershell",
                        lambda *a, **k: ("", "超时（>45s）"))
    data = kernel_instability.collect(use_cache=False)
    assert data["ok"] is False
    assert "超时" in data["error"]
    assert data["events"] == []


def test_collect_caches_and_can_bypass(monkeypatch):
    calls: list[int] = []

    def fake(*_args, **_kwargs):
        calls.append(1)
        return _SAMPLE, ""

    monkeypatch.setattr(kernel_instability, "_run_powershell", fake)
    kernel_instability.collect()
    kernel_instability.collect()
    assert len(calls) == 1                      # 崩溃包 + 诊断包连着走，只跑一次
    kernel_instability.collect(use_cache=False)
    assert len(calls) == 2


def test_non_windows_platform_is_reported(monkeypatch):
    monkeypatch.setattr(kernel_instability, "os", types.SimpleNamespace(name="posix"))
    text, error = kernel_instability._run_powershell("anything")
    assert text == ""
    assert "非 Windows" in error


def test_script_pins_time_semantics_and_output_width():
    """钉住两处**实测踩过**的写法：时间必须走 `DateTimeOffset`、输出必须加宽。

    少了前者，「距本次启动最近的一条」会整整错一个时区；少了后者，`Message` 里的
    exe 路径会被 `Format-List` 折成两半，再也拼不回来。
    """
    script = kernel_instability._script(30)
    assert "[DateTimeOffset]$_.TimeCreated" in script
    assert "ToUnixTimeSeconds()" in script
    assert "LocalDateTime" in script
    assert "Out-String -Width" in script
    assert "AddDays(-30)" in script


# ---------------------------------------------------------------------------
# 渲染：判据纪律（"没查到" 绝不能读成 "机器是稳的"）
# ---------------------------------------------------------------------------
def test_failure_text_never_reads_as_machine_is_stable():
    lines = kernel_instability.summary_lines(
        {"ok": False, "error": "超时（>45s）", "events": [], "counts": {}, "bugchecks": {}})
    text = "\n".join(lines)
    assert "没能读到 System 日志" in text
    assert "超时" in text
    assert "不等于" in text                      # 必须写明「没查到 ≠ 稳」
    assert "窗口内没有蓝屏" not in text           # 没采到就不许说"没有事件"


def test_empty_window_is_stated_and_flagged_as_background():
    data = kernel_instability._parse_output(
        f"MC-ERR1:\n{kernel_instability._SPLIT}\nMC-ERR2:\n", 30, 1.0)
    text = "\n".join(kernel_instability.summary_lines(data))
    assert "窗口内没有蓝屏" in text
    assert "相关不等于因果" in text               # 背景判据的声明必须在
    assert "背景判据" in text


def test_timeline_and_since_reference_are_rendered():
    data = kernel_instability._parse_output(_SAMPLE, 30, 1.0)
    since = _epoch(_T3) + 3600                    # 最后一条之后 1 小时
    text = "\n".join(kernel_instability.summary_lines(data, since=since))
    assert "蓝屏（BugCheck） 1 次" in text
    assert "`0x00000116` ×1" in text
    assert _T1 in text                            # 时间轴带绝对时间
    assert "距本次启动最近的一条" in text
    assert _T3 in text                            # 取的是启动前最近那条


def test_since_reference_is_omitted_without_events():
    data = kernel_instability._parse_output(
        f"MC-ERR1:\n{kernel_instability._SPLIT}\nMC-ERR2:\n", 30, 1.0)
    text = "\n".join(kernel_instability.summary_lines(data, since=time.time()))
    assert "距本次启动最近的一条" not in text


def test_human_delta_scales():
    assert kernel_instability._human_delta(45) == "45 秒"
    assert kernel_instability._human_delta(600) == "10 分钟"
    assert kernel_instability._human_delta(7200) == "2.0 小时"
    assert kernel_instability._human_delta(200000) == "2.3 天"
