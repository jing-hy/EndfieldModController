"""记忆日志（`docs/AI-记忆日志.md`）的导出：**不能炸、不能漏、不能泄路径**。

用户 2026-10-03 的要求链：「还有 dsh 的记忆也一起上传源码」→「每次传源码记忆都一起」
→「或者不传记忆但是需要一个类似记忆的日志，每次上传」。
落地成 `scripts/memory_log.py`：每次 `push.py` 推送前刷新并单独提交这一份 markdown。

本文件钉住三件事：
① 七张表的**列不一致**（`user`/`soul` 没有 `project`，`fact`/`lesson` 没有 `subcategory`，
   `project` 表没有 `goal`）—— 第一版写死列名时每条 SELECT 都抛错被吞成空，导出了 **0 条**；
② 归档条目不许进日志，别的项目的条目也不许混进来；
③ 本机用户名路径要**脱敏**（`C:\\Users\\<user>`），技术路径保留。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import memory_log  # noqa: E402


SCHEMA = {
    # 故意**照抄真实库的列差异**（这正是当初导出 0 条的根因）
    "lesson": ("id", "title", "content", "importance", "keywords", "status",
               "corrected", "project", "updated_at"),
    "project": ("id", "title", "content", "importance", "keywords", "status",
                "project", "subcategory", "updated_at"),
    "rules": ("id", "title", "content", "importance", "keywords", "status",
              "project", "updated_at"),
    "fact": ("id", "title", "content", "importance", "keywords", "status",
             "project", "updated_at"),
    "topic": ("id", "title", "content", "importance", "keywords", "status",
              "goal", "project", "updated_at"),
    "user": ("id", "title", "content", "importance", "keywords", "status", "updated_at"),
}


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    for table, columns in SCHEMA.items():
        conn.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
    rows = {
        "lesson": [
            ("l1", "", "本项目的一条教训：" + "A" * 30, 3, "", "active", 0, "modecontroller", 1700000000000),
            ("l2", "", "已归档的旧教训", 1, "", "archived", 0, "modecontroller", 1700000000001),
            ("l3", "", "别的项目的教训", 1, "", "active", 0, "sbm", 1700000000002),
        ],
        "project": [
            ("p1", "", "项目结构：backend/web/scripts", 3, "", "active", "modecontroller", "structure", 1700000000003),
        ],
        "user": [
            ("u1", "", r"用户机器路径 C:\Users\Administrator\Downloads 要脱敏", 3, "", "active", 1700000000004),
        ],
    }
    for table, items in rows.items():
        placeholders = ", ".join("?" * len(SCHEMA[table]))
        conn.executemany(f"INSERT INTO {table} VALUES ({placeholders})", items)
    conn.commit()
    conn.close()
    return path


def test_exports_rows_despite_uneven_columns(db: Path) -> None:
    """★ 回归：七张表列不一致也要能导出（当初写死列名 ⇒ 0 条）。"""
    text, total = memory_log.build(db, "modecontroller")

    assert total >= 3, f"导出条数太少（列名写死那次的 bug）：{total}"
    assert "本项目的一条教训" in text
    assert "项目结构：backend/web/scripts" in text


def test_skips_archived_and_other_projects(db: Path) -> None:
    text, _ = memory_log.build(db, "modecontroller")

    assert "已归档的旧教训" not in text, "archived 条目不该进日志"
    assert "别的项目的教训" not in text, "非本项目的条目不该混进来"


def test_scrubs_home_directory(db: Path) -> None:
    """本机**主目录**路径要脱敏（公开仓库里不该出现具体用户名）。

    注意只断言 `C:\\Users\\<名字>` 这一种形态：pytest 的临时目录名里也可能恰好带
    用户名（`pytest-of-Administrator`），那跟脱敏无关。
    """
    text, _ = memory_log.build(db, "modecontroller")

    assert r"C:\Users\Administrator" not in text, "主目录路径没被脱敏"
    assert r"C:\Users\<user>" in text


def test_timestamp_is_human_readable(db: Path) -> None:
    """毫秒时间戳要格式化成日期，别把 1700000000000 直接印出来。"""
    text, _ = memory_log.build(db, "modecontroller")

    assert "1700000000000" not in text
    assert "2023-11-15" in text or "2023-11-14" in text or "2023-11-16" in text


def test_missing_db_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    """没有记忆库（别人 clone 下来跑）时**不能抛异常** —— 它挂在 push 流程里。"""
    monkeypatch.setattr(sys, "argv", ["memory_log.py", "--db", str(tmp_path / "nope.db"), "--print"])
    assert memory_log.main() == 0
