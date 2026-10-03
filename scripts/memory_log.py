#!/usr/bin/env python
"""把本工作区的「记忆」导出成一份可读的开发日志：`docs/AI-记忆日志.md`。

**用户要求（2026-10-03）**：「每次传源码，记忆（或一份**类似记忆的日志**）都一起上传」
—— 不是把 `memory.db` 传上去（那是二进制、还夹着本机路径与第三方反馈者的设备信息），
而是导出成**可读、可 diff、跟着每次 push 一起更新**的 markdown，让人（或下一轮 AI）
在仓库里就能看到"当时为什么这么改、踩过什么坑"。

**做法**：读 `<工作区>/.dsh-meow/memory.db`（meow-memory 的七张表），
挑出与**本项目 + 全局**相关的条目，按层级分组、按最后更新时间排序，整份重写目标文件。
跑一次很快（毫秒级），所以直接挂在 `scripts/push.py` 里 —— **每次推送都会刷新它**。

用法：
    python scripts/memory_log.py                 # 写 docs/AI-记忆日志.md
    python scripts/memory_log.py --out other.md  # 换输出文件
    python scripts/memory_log.py --print         # 只打印条数，不写文件
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / ".dsh-meow" / "memory.db"
DEFAULT_OUT = ROOT / "docs" / "AI-记忆日志.md"

# 表名 = level；顺序也是文档里的章节顺序
LEVELS = ("rules", "project", "topic", "lesson", "fact", "user", "soul")
LEVEL_TITLES = {
    "rules": "设计原则 / 行为准则",
    "project": "项目记忆（结构 / 决策 / 部署 / 待办）",
    "topic": "话题（一件事的前因后果）",
    "lesson": "经验教训（被纠正过的、踩过的坑）",
    "fact": "事实（细碎的原子信息）",
    "user": "用户偏好与环境（**含个人信息，公开前请自行取舍**）",
    "soul": "AI 自身",
}
SUBCATEGORY_TITLES = {
    "overview": "项目概述",
    "structure": "项目结构",
    "decisions": "技术决策",
    "quotes": "用户原话",
    "ops": "部署与数据",
    "todo": "待办",
}

# 轻量脱敏：只抹掉本机用户名路径（"C:\Users\Administrator"），其余技术路径保留 ——
# 那些是项目自己用的数据根（`D:\zmdmod\...`），对读日志的人是有用信息。
_HOME_RE = re.compile(r"[A-Za-z]:\\\\?Users\\\\?[^\\\\\s\"']+", re.IGNORECASE)


def _scrub(text: str) -> str:
    return _HOME_RE.sub(r"C:\\Users\\<user>", text or "")


def _rel(path: Path) -> str:
    """日志里只写**相对仓库**的路径 —— 免得把本机用户名夹在临时/绝对路径里带出去。"""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except (ValueError, OSError):
        return _scrub(str(path))


def _rows(conn: sqlite3.Connection, level: str, project: str) -> list[dict]:
    """取某个 level 下与本项目相关的条目（project 命中项目名，或标成全局）。

    ⚠️ 七张表的列**并不一致**（`user`/`soul` 没有 `project`，`fact`/`lesson` 没有
    `subcategory`，`project` 表没有 `goal`）—— 第一版写死了列名，结果每条
    `SELECT` 都抛 `sqlite3.Error` 被吞成空 ⇒ 导出的日志 0 条。现在按实际列取交集。
    """
    try:
        available = [item[1] for item in conn.execute(f"PRAGMA table_info({level})")]
    except sqlite3.Error:
        return []
    wanted = [name for name in ("id", "title", "content", "importance", "keywords", "status",
                                "project", "subcategory", "goal", "updated_at")
              if name in available]
    if not wanted:
        return []
    try:
        cur = conn.execute(f"SELECT {', '.join(wanted)} FROM {level}")
    except sqlite3.Error:
        return []
    columns = [item[0] for item in cur.description]
    out: list[dict] = []
    for row in cur.fetchall():
        item = dict(zip(columns, row))
        if str(item.get("status") or "") == "archived":
            continue                      # 归档的（= 已删除/作废）不进日志
        owned = str(item.get("project") or "")
        if level in ("rules", "fact", "lesson", "topic"):
            if project not in owned and "全局" not in owned:
                continue
        elif level == "user":
            pass                          # 用户偏好是全局的，全放
        elif level == "soul":
            pass
        out.append(item)
    out.sort(key=lambda item: str(item.get("updated_at") or ""))
    return out


def build(db: Path, project: str) -> tuple[str, int]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sections: list[str] = []
        total = 0
        for level in LEVELS:
            rows = _rows(conn, level, project)
            if not rows:
                continue
            total += len(rows)
            body: list[str] = [f"## {LEVEL_TITLES[level]}（{len(rows)} 条）", ""]
            if level == "project":
                for sub in SUBCATEGORY_TITLES:
                    group = [r for r in rows if str(r.get("subcategory") or "") == sub]
                    if not group:
                        continue
                    body.append(f"### {SUBCATEGORY_TITLES[sub]}")
                    body.append("")
                    body.extend(_render(group))
            else:
                body.extend(_render(rows))
            sections.append("\n".join(body))
    finally:
        conn.close()

    head = [
        "# AI 记忆日志（自动生成，请勿手改）",
        "",
        "> 这份文件由 `scripts/memory_log.py` 从工作区记忆库导出，**每次 `push.py` 推送前自动刷新**。",
        "> 目的：让「当时为什么这么改、踩过什么坑」跟着源码一起留在仓库里。",
        "> 想改内容 → 改记忆库（用记忆工具），再跑一次本脚本；不要直接编辑本文件。",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 来源：`{_rel(db)}`",
        f"- 条目：{total} 条（已跳过 archived / 其它项目的条目）",
        "",
        "---",
        "",
    ]
    return "\n".join(head + sections) + "\n", total


def _stamp(value: object) -> str:
    """`updated_at` 存的是**毫秒时间戳**（老条目可能是 ISO 串）—— 统一成 `YYYY-MM-DD HH:MM`。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        seconds = int(text) / (1000 if len(text) >= 12 else 1)
        try:
            return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return text
    return text[:16].replace("T", " ")


def _render(rows: list[dict]) -> list[str]:
    out: list[str] = []
    for item in rows:
        content = _scrub(str(item.get("content") or "")).strip()
        title = str(item.get("title") or "").strip()
        goal = str(item.get("goal") or "").strip()
        # 标题大多是空的 ⇒ 用正文开头当标题，日志才扫得动
        label = title or goal or (content[:28].replace("\n", " ") + ("…" if len(content) > 28 else ""))
        stamp = _stamp(item.get("updated_at"))
        keywords = item.get("keywords") or ""
        if isinstance(keywords, (bytes, bytearray)):
            keywords = keywords.decode("utf-8", "replace")
        out.append(f"### {label or '（无内容）'}")
        if stamp:
            out.append(f"*{stamp}*")
        out.append("")
        out.append(content)
        if keywords:
            out.append("")
            out.append(f"`关键词：{keywords}`")
        out.append("")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="把记忆库导出成 docs/AI-记忆日志.md")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--project", default="modecontroller")
    parser.add_argument("--print", dest="dry", action="store_true", help="只报条数，不写文件")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.is_file():
        # 记忆库不在（例如别人 clone 下来跑）⇒ **静默跳过**，绝不阻断 push。
        print(f"[memory-log] 没有记忆库 {db}，跳过（不影响推送）")
        return 0

    text, total = build(db, args.project)
    if args.dry:
        print(f"[memory-log] {total} 条（未写文件）")
        return 0
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"[memory-log] 已写 {out.relative_to(ROOT)}（{total} 条 / {len(text)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
