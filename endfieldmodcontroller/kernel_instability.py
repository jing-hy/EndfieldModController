"""机器侧稳定性 —— System 日志里的内核证据（蓝屏 / 非正常关机 / WHEA / 关机发起者）。

**为什么要它（2026-10-07 加）**：本程序查"是不是外部把游戏干掉了"一直只看
Application 日志，而"**这台机器自己稳不稳**"——内核蓝屏（`BugCheck`）、非正常关机
（`Kernel-Power 41` / `EventLog 6008`）、硬件错误（`WHEA-Logger`）、谁发起的关机
（`User32 1074`）——**一条都采不到**。实测证据：一份 283 项的诊断包里，
`windows-events-*.log` 的 Provider 只有 `Windows Error Reporting` 与
`RestartManager` 两类，**System 侧 0 条**（现有窗口只有"崩溃前 5 分钟"，
30 天的回溯窗口根本不存在）。这条缺口会让「游戏随机起不来」永远没有机器侧对照。

**定位：背景判据，不是结论。**（三条纪律，缺一条就不要这段数据）
1. **不下结论** —— 只如实陈述"窗口内有过哪些内核级事件 + 时间轴"，**不参与
   `crashwatch.classify_cause()` 的归因选择**（不改任何优先级）。蓝屏是**整机**事件：
   它既不能证明、也不能否定本次故障由 Mod 侧引起；文本里必须写明
   「**相关不等于因果**」。
2. **拿不到 ≠ 稳** —— 采集失败一律如实写"没查到"并给出原因，**绝不**渲染成
   "这台机器没有问题"（那会把"采不到"变成一条错误的正面判据）。
3. **要能对照** —— 时间轴带绝对时间；调用方给了"本次启动时刻"时，额外汇总
   "距本次启动最近的一条"，让人自己看时间关系，而不是替他下判断。

**采集方式**：一次 PowerShell 调用、两条 `Get-WinEvent` 查询（按 `Id` 一网打尽
41/1001/6008/1074，按 `ProviderName` 抓 WHEA）。**解析/汇总/渲染全部离线可测**，
只有 `collect()` 会真起子进程（测试里打桩 `_run_powershell` 即可）。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# 采集窗口：30 天。「先非正常关机、之后游戏才起不来」这种时间关系需要几天前的证据，
# 只取"崩溃前 5 分钟"永远看不到 —— 那正是这条判据此前一直缺失的原因。
WINDOW_DAYS = 30
# 每条事件的 Message 只留这么多字：蓝屏/关机事件的正文很长，整段带进报告会把
# summary.txt 撑爆，而判据只需要"哪一类 + 关键码 / 发起者"。
MESSAGE_LIMIT = 600
# 时间轴最多列几条（最近的在最后）。
TIMELINE_LIMIT = 15

_SPLIT = "===MC-KERNEL-SPLIT==="
_QUERY_TIMEOUT = 45.0
_CACHE_TTL = 60.0
# 一次崩溃会连着走「崩溃包」与「手动诊断包」两条路，不能为此跑两遍 PowerShell。
_CACHE: tuple[float, dict[str, Any]] | None = None

# 按 Id 一网打尽（比按 ProviderName 稳：provider 名会随系统语言/版本漂）：
#   41   Kernel-Power             非正常关机 / 断电（未先正常关机就重启）
#   1001 WER-SystemErrorReporting 蓝屏（Message 里带 bugcheck 码）
#   6008 EventLog                 上次关机是意外的
#   1074 User32                   谁发起的关机 / 重启（含进程名与原因）
_ID_QUERY_IDS: tuple[int, ...] = (41, 1001, 6008, 1074)
# WHEA 只有单一 provider，且 Id 随版本变（1/17/18/19/20/47…）⇒ 按 provider 抓。
_WHEA_PROVIDER = "Microsoft-Windows-WHEA-Logger"
_MAX_EVENTS = 200

_KIND_BY_ID = {
    1001: "bugcheck",
    41: "unexpected_shutdown",
    6008: "unexpected_shutdown",
    1074: "shutdown_initiator",
}
KIND_LABELS = {
    "bugcheck": "蓝屏（BugCheck）",
    "unexpected_shutdown": "非正常关机",
    "whea": "硬件错误（WHEA）",
    "shutdown_initiator": "关机/重启发起",
    "other": "其它内核事件",
}

# `Format-List` 的字段行：`At               : 2026-10-07 12:22:08`
_FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*:\s?(.*)$")
# PowerShell 侧带回来的错误行（区分"没有事件"与"查询失败"的关键）
_ERR_RE = re.compile(r"^MC-ERR(\d):(.*)$")
# 「没有事件」是**正常结果**，不是失败；其余错误才算采集失败。
# ⚠️ 中文文案是**随系统语言变**的，实测本机是「找不到任何与指定的选择条件匹配的事件。」
#    （既不是"没有找到符合…"也不是"未找到符合…"）⇒ 按"否定词 + 事件"判，别写死整句。
_NO_EVENTS_HINTS = ("no events were found", "no matching events", "no events")
_NO_EVENTS_WORDS = ("没有找到", "未找到", "找不到")
_HEX_CODE_RE = re.compile(r"0x[0-9a-fA-F]{8,16}")
_EXE_RE = re.compile(r"([A-Za-z]:\\[^\"'\s()]+\.exe)", re.I)


# ---------------------------------------------------------------------------
# 采集（唯一会起子进程的地方）
# ---------------------------------------------------------------------------
def _script(days: int) -> str:
    """两条查询写进同一次 PowerShell 调用 —— 省掉一次进程启动（各约 1 秒）。

    ⚠️ 两个实测踩过的坑，别改回去：
    * **时间必须走 `[DateTimeOffset]`**：`Get-WinEvent` 的 `TimeCreated` 是
      `Kind=Utc` 的 `DateTime`，用 `$_.TimeCreated - [datetime]::new(1970,1,1,0,0,0,Local)`
      算出来的 Epoch **比真值多一个时区偏移（本机 8 小时）** ⇒ 时间轴排序没错，
      但"距本次启动最近的一条"会选错（实测选了 13.7 小时前的那条，真值是 21.7 小时）。
    * **`Out-String -Width 4096`**：`Format-List` 会按宿主宽度把长值折行，而
      `Message` 里的 exe 路径一旦被折断（`…StartMenuExper` / `ienceHost.exe`），
      就再也拼不回一个可匹配的路径了。加宽之后一条事件就是一行值。
    """
    select = (
        "Select-Object "
        "@{n='At';e={([DateTimeOffset]$_.TimeCreated).LocalDateTime.ToString('yyyy-MM-dd HH:mm:ss')}},"
        "@{n='Epoch';e={[int64]([DateTimeOffset]$_.TimeCreated).ToUnixTimeSeconds()}},"
        "Id,ProviderName,"
        "@{n='Message';e={if ($_.Message) { ($_.Message -replace '\\s+',' ').Trim() } else { '' }}} "
        "| Format-List | Out-String -Width 4096"
    )
    ids = ",".join(str(i) for i in _ID_QUERY_IDS)
    return (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$since=(Get-Date).AddDays(-{days});"
        f"$e1=@();@(Get-WinEvent -FilterHashtable @{{LogName='System';Id=@({ids});"
        f"StartTime=$since}} -MaxEvents {_MAX_EVENTS} "
        f"-ErrorAction SilentlyContinue -ErrorVariable e1) | {select};"
        "Write-Output ('MC-ERR1:' + ((@($e1) | ForEach-Object { $_.ToString() }) -join ' | '));"
        f"Write-Output '{_SPLIT}';"
        f"$e2=@();@(Get-WinEvent -FilterHashtable @{{LogName='System';"
        f"ProviderName='{_WHEA_PROVIDER}';StartTime=$since}} -MaxEvents {_MAX_EVENTS} "
        f"-ErrorAction SilentlyContinue -ErrorVariable e2) | {select};"
        "Write-Output ('MC-ERR2:' + ((@($e2) | ForEach-Object { $_.ToString() }) -join ' | '))"
    )


def _run_powershell(script: str, *, timeout: float = _QUERY_TIMEOUT) -> tuple[str, str]:
    """跑一段 PowerShell，返回 `(stdout, 错误说明)`。**永远不抛异常**。

    ⚠️ 两个必须：① 命令前把 `[Console]::OutputEncoding` 设为 UTF-8 —— PowerShell 5.1
    默认按系统 ANSI（中文机 = GBK）写管道，按 UTF-8 解码会得到一串乱码；
    ② `CREATE_NO_WINDOW` —— 用户明确要求"启动与运行过程中不允许出现任何 cmd 黑窗"。
    """
    if os.name != "nt":
        return "", "非 Windows 平台，跳过"
    prefix = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
              "$OutputEncoding=[System.Text.Encoding]::UTF8;")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return "", f"超时（>{timeout:g}s）"
    except Exception as exc:  # noqa: BLE001 —— 采集失败绝不影响主流程
        return "", f"调用失败: {exc}"
    text = result.stdout or ""
    if not text.strip() and (result.stderr or "").strip():
        return "", f"stderr: {(result.stderr or '').strip()[:300]}"
    return text, ""


# ---------------------------------------------------------------------------
# 解析 / 汇总（纯函数，离线可测）
# ---------------------------------------------------------------------------
def _parse_records(text: str) -> list[dict[str, str]]:
    """把 `Format-List` 的输出切成一条条记录。

    ⚠️ **不能"按空行切块"**：`Message` 正文自带空行与缩进续行，那样切会把
    多条记录并成一条（实测那种写法下 6 条只解析出 1 条）。
    这里的规则：**顶格且形如 `字段 : 值` 的行**开新字段；**缩进行**一律并进上一个字段
    （续行拼回）；同名字段再次出现 ⇒ 上一条记录结束。
    """
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        match = _FIELD_RE.match(line)
        if match and not line[:1].isspace():
            name, value = match.group(1), match.group(2).strip()
            if name in current:
                records.append(current)
                current = {}
            current[name] = value
        elif current:
            key = next(reversed(current))
            current[key] = f"{current[key]} {line.strip()}".strip()
    if current:
        records.append(current)
    return records


def _classify(event_id: int, provider: str) -> str:
    if "whea" in (provider or "").lower():
        return "whea"
    return _KIND_BY_ID.get(event_id, "other")


def _detail(kind: str, message: str) -> str:
    """给时间轴一行能一眼看懂的关键信息（蓝屏码 / 发起关机的进程）。"""
    if kind in ("bugcheck", "whea"):
        match = _HEX_CODE_RE.search(message or "")
        if match:
            code = match.group(0)
            return "0x" + code[2:].upper()
        return ""
    if kind == "shutdown_initiator":
        match = _EXE_RE.search(message or "")
        name = Path(match.group(1)).name if match else ""
        low = (message or "").lower()
        if "重启" in (message or "") or "restart" in low:
            what = "重启"
        elif "关机" in (message or "") or "shutdown" in low:
            what = "关机"
        else:
            what = ""
        return " / ".join(item for item in (name, what) if item)
    return ""


def _is_no_events(text: str) -> bool:
    """这一条错误是不是「**没有符合条件的事件**」。

    ⚠️ 中文文案随系统语言变（实测本机：「找不到任何与指定的选择条件匹配的事件。」），
    所以按"否定词 + 事件"判，别写死整句。
    """
    if not text:
        return False
    low = text.lower()
    if any(hint in low for hint in _NO_EVENTS_HINTS):
        return True
    return "事件" in text and any(word in text for word in _NO_EVENTS_WORDS)


def _significant_error(raw: str) -> str:
    """从 `MC-ERRn:` 里挑出**真正的失败**。

    「没有事件符合条件」是正常结果（窗口内就是没有蓝屏），不算失败 ——
    把这两种混起来，就等于把"没查到"当成"机器是稳的"，那是错的。
    """
    parts = [item.strip() for item in (raw or "").split("|")]
    kept = [item for item in parts if item and not _is_no_events(item)]
    return " | ".join(kept)


def _parse_output(text: str, days: int, now: float) -> dict[str, Any]:
    blocks = text.split(_SPLIT)
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for block in blocks:
        clean: list[str] = []
        for line in block.splitlines():
            match = _ERR_RE.match(line.strip())
            if match:
                message = _significant_error(match.group(2))
                if message:
                    errors.append(message)
                continue
            clean.append(line)
        for fields in _parse_records("\n".join(clean)):
            event = _event_from_fields(fields)
            if event is not None:
                events.append(event)
    events.sort(key=lambda item: (item["at"] or 0.0, item["at_text"]))
    return _summarize(events, days=days, errors=errors, now=now)


def _event_from_fields(fields: dict[str, str]) -> dict[str, Any] | None:
    try:
        event_id = int((fields.get("Id") or "0").strip())
    except ValueError:
        event_id = 0
    provider = (fields.get("ProviderName") or "").strip()
    try:
        at = float((fields.get("Epoch") or "0").strip())
    except ValueError:
        at = 0.0
    at_text = (fields.get("At") or "").strip()
    if not at_text and not at:
        return None                     # 既没时间也没字段 ⇒ 不是一条事件
    message = (fields.get("Message") or "").strip()[:MESSAGE_LIMIT]
    kind = _classify(event_id, provider)
    return {
        "at": at,
        "at_text": at_text,
        "kind": kind,
        "event_id": event_id,
        "provider": provider,
        "message": message,
        "detail": _detail(kind, message),
    }


def _summarize(events: list[dict[str, Any]], *, days: int, errors: list[str],
               now: float) -> dict[str, Any]:
    counts: dict[str, int] = {}
    bugchecks: dict[str, int] = {}
    for event in events:
        counts[event["kind"]] = counts.get(event["kind"], 0) + 1
        if event["kind"] == "bugcheck" and event["detail"]:
            bugchecks[event["detail"]] = bugchecks.get(event["detail"], 0) + 1
    return {
        "ok": True,
        "window_days": days,
        "collected_at": now,
        "events": events,
        "counts": counts,
        "bugchecks": bugchecks,
        # 采集过程中**真正的**错误（"没有事件"已被剔除）。有它就说明这次数据不可靠。
        "error": " | ".join(errors),
    }


def collect(days: int = WINDOW_DAYS, *, use_cache: bool = True) -> dict[str, Any]:
    """采一次机器侧稳定性。返回结构见 `_summarize`；**失败时 `ok=False` + `error`**。

    ⚠️ 永远不要因为 `ok=False` 就写"机器是稳的" —— 那两件事完全不同。
    """
    global _CACHE
    now = time.time()
    if use_cache and _CACHE is not None and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]
    text, failure = _run_powershell(_script(days))
    if failure:
        data: dict[str, Any] = {
            "ok": False, "window_days": days, "collected_at": now,
            "events": [], "counts": {}, "bugchecks": {}, "error": failure,
        }
    else:
        data = _parse_output(text, days, now)
    if use_cache:
        _CACHE = (now, data)
    return data


# ---------------------------------------------------------------------------
# 渲染（报告里那一段）
# ---------------------------------------------------------------------------
def _human_delta(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(seconds)} 秒"
    if seconds < 5400:
        return f"{int(seconds / 60)} 分钟"
    if seconds < 172800:
        return f"{seconds / 3600:.1f} 小时"
    return f"{seconds / 86400:.1f} 天"


def summary_lines(data: dict[str, Any] | None, *, since: float | None = None) -> list[str]:
    """渲染成报告里的一段（**自带标题**，调用方不要再加一条）。

    `since` = 本次启动时刻（可选）。给了就额外汇总"距本次启动最近的一条"，
    只做**对照**，不下结论。
    """
    lines = ["-- 机器侧稳定性（System 日志；**背景判据，不是结论**）--"]
    if not data or not data.get("ok"):
        reason = (data or {}).get("error") or "未知原因"
        lines.append(f"  （没能读到 System 日志：{reason}）")
        lines.append("  ⚠️「没查到」**不等于**「机器是稳的」—— 这条判据这次是空的，别当结论用。")
        return lines

    events = data.get("events") or []
    lines.append(f"  窗口：最近 {data.get('window_days')} 天；"
                 f"内核级事件 {len(events)} 条")
    if data.get("error"):
        lines.append(f"  ⚠️ 采集过程中有错误（数据可能不全）：{data['error']}")

    if not events:
        lines.append("  （窗口内没有蓝屏 / 非正常关机 / WHEA / 关机发起记录）")
    else:
        counts = data.get("counts") or {}
        parts = [f"{KIND_LABELS.get(kind, kind)} {count} 次"
                 for kind, count in sorted(counts.items()) if count]
        lines.append("  分类：" + "；".join(parts))
        if data.get("bugchecks"):
            codes = "、".join(f"`{code}` ×{count}"
                              for code, count in sorted(data["bugchecks"].items()))
            lines.append(f"  蓝屏代码：{codes}")
        lines.append(f"  时间轴（最近 {min(len(events), TIMELINE_LIMIT)} 条）：")
        for event in events[-TIMELINE_LIMIT:]:
            label = KIND_LABELS.get(event["kind"], event["kind"])
            detail = f"（{event['detail']}）" if event.get("detail") else ""
            lines.append(f"    {event['at_text']}  {label}{detail}")

    if since and events:
        before = [event for event in events if event["at"] and event["at"] <= float(since) + 600]
        if before:
            event = before[-1]
            gap = _human_delta(float(since) - event["at"]) if event["at"] else "?"
            label = KIND_LABELS.get(event["kind"], event["kind"])
            lines.append(f"  距本次启动最近的一条：{event['at_text']} {label}"
                         f"（提前 {gap}）")

    lines.append("  说明：以上只说明「这台机器在窗口内有过内核级异常 / 异常重启」。"
                 "蓝屏是**整机**事件，**相关不等于因果** —— "
                 "不能据此判定本次故障由它引起，也不能据此把 Mod 侧的原因排除掉。")
    return lines
