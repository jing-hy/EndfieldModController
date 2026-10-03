"""前端「动作名」不许对不上（2026-10-03 用户：「Mod 的更多中点击更改角色归属无反应」）。

**这次的三个真 bug 叠在一起**：
① 卡片上的黄色标签调 `menuAct('assign', mod)`，而函数**只看 `menu.value`** —— 那时浮层根本
   没打开 ⇒ `if (!m) return` 当场返回 ⇒ 点了完全没反应；
② `'assign'` 这个动作名**一个分支都没有**（script 里只写了 `'character'`）；
③ catch 是空的，本地异常（TypeError 之类）被静默吞掉，界面上同样"没反应"。

`vite build` 不会报这类错（字符串对不上不是语法错误），所以单独钉一条静态回归：
**模板里传给菜单处理函数的每个动作名，函数体内必须有对应分支**。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"
CASES = ["ModLibraryPage.vue", "AssistPage.vue"]


def _parts(name: str) -> tuple[str, str]:
    """取（`<template>` 段, `menuAct()` 的函数体）。函数体按大括号配平截取，
    免得把后面别的函数的 catch 也算进来。"""
    src = (PAGES / name).read_text(encoding="utf-8")
    # 用 `rpartition` 取最后一个完整模板块：`<script setup>` 的注释里也会出现
    # `<template>` 字样，从头 split 会截错地方（第一次写这条测试就踩了）。
    head, _, _ = src.rpartition("</template>")
    template = head.rpartition("<template>")[2]

    start = src.index("async function menuAct(")
    open_at = src.index("{", start)
    depth = 0
    for index in range(open_at, len(src)):
        char = src[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return template, src[open_at:index + 1]
    raise AssertionError(f"{name} 里 menuAct() 的大括号不配平")


@pytest.mark.parametrize("name", CASES)
def test_every_menu_action_has_a_branch(name: str) -> None:
    template, body = _parts(name)
    used = set(re.findall(r"menuAct\(\s*'([A-Za-z]+)'", template))
    handled = set(re.findall(r"act\s*===\s*\"([A-Za-z]+)\"", body))
    missing = sorted(used - handled)
    assert not missing, (
        f"{name}：模板里传了这些动作名，但 menuAct() 里没有对应分支 ⇒ 点了没反应：{missing}"
        f"（已实现：{sorted(handled)}）"
    )


@pytest.mark.parametrize("name", CASES)
def test_catch_is_not_silent(name: str) -> None:
    """本地异常不许被空 catch 吞掉 —— 那正是用户看到的“点了没反应”。"""
    _, body = _parts(name)
    # 取**最外层**那个 catch（函数体末尾那个）：内部还有"查工具失败就直接试"之类的小 catch
    tail = body.rsplit("} catch (e)", 1)
    assert len(tail) == 2, f"{name}：menuAct 的 catch 结构变了，请更新这条测试"
    handler = tail[1].split("}", 1)[0]
    assert "console.error" in handler or "showAlert" in handler, \
        f"{name}：menuAct 的 catch 把错误静默吞掉了（用户看到的是“没反应”）"


def test_card_badge_passes_the_mod_itself() -> None:
    """卡片上的标签必须在没打开浮层时也能工作（第二参数 = 那个 mod）。"""
    template, _ = _parts("ModLibraryPage.vue")
    calls = re.findall(r"menuAct\('assign',\s*([A-Za-z_$][\w$]*)\)", template)
    assert calls, "卡片标签不再调用 menuAct('assign', …) 了？请同步更新这条回归"
    assert all(call == "m" for call in calls), f"卡片标签要把卡片那一项传进去：{calls}"
