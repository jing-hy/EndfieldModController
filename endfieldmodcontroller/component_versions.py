"""读「随包组件版本表」并给出「有哪些组件该更新了」。

用户 2026-10-03：「那个一键启动检查更新**还是要加**，但是是**随包资源里配一张版本表**，
每次比对那个表，然后**随管理器更新而更新**，对旧版本**没有这个表，如果表不存在就跳过**」。

**性质**：纯本地读取（表随 exe 走），**不联网** —— 所以放进"一键启动前"的路径
也不会有任何等待（这正是当初把联网检查拿掉的原因：它要 6.1 秒）。

**旧版本兼容**：表不存在 ⇒ `load()` 返回 `{}` ⇒ `outdated()` 返回空列表 ⇒ 调用方跳过。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TABLE_NAME = "component_versions.json"


def _table_path() -> Path | None:
    """找到随包的那张表。打包后走 `sys._MEIPASS`（与其它 `--add-data` 资源一致）。"""
    candidates: list[Path] = []
    frozen = getattr(sys, "frozen", False)
    meipass = getattr(sys, "_MEIPASS", None)
    if frozen and meipass:
        candidates.append(Path(meipass) / "endfieldmodcontroller" / TABLE_NAME)
    # 源码运行 / 兜底：模块旁边
    candidates.append(Path(__file__).resolve().parent / TABLE_NAME)
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def load() -> dict[str, Any]:
    """读表；**不存在或读不动都返回空字典**（调用方据此跳过，不报错）。"""
    path = _table_path()
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ver_tuple(text: str) -> tuple[int, ...]:
    """把 `v1.2.3` / `1.2.3` 这类版本串转成可比较的元组（非数字段直接忽略）。"""
    import re

    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(x) for x in parts[:4]) if parts else ()


def outdated(installed: dict[str, str]) -> list[dict[str, str]]:
    """比对「本机已装版本」与「表里的最新版」，返回**该更新**的组件列表。

    `installed` 形如 `{"XXMI": "v2.2.1", "EFMI": "v1.4.8", ...}`；
    返回 `[{"key","display","current","latest"}, ...]`，没有任何待更新时返回 `[]`。

    ⚠️ **只用"本地版本"与"表里版本"两个数**：
    * 本地没有版本（未安装）**不算**"该更新" —— 那是依赖页"安装缺失"的事；
    * 表里留空（`latest` 为空串）**跳过**，避免误报。
    """
    table = load()
    if not table:
        return []
    out: list[dict[str, str]] = []
    for section in ("builtin", "external"):
        rows = table.get(section)
        if not isinstance(rows, dict):
            continue
        for key, info in rows.items():
            if not isinstance(info, dict):
                continue
            latest = str(info.get("latest") or "").strip()
            current = str(installed.get(key) or "").strip()
            if not latest or not current:
                continue
            if _ver_tuple(latest) > _ver_tuple(current):
                out.append({
                    "key": key,
                    "display": str(info.get("display") or key),
                    "current": current,
                    "latest": latest,
                })
    return out
