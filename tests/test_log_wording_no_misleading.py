"""日志文案不许误导排查（2026-10-07 一天里踩到第三处）。

用户被误导的两次原话：
  · 「为什么我没开dlss5日志也说按dlss5」        ← `DLSS5 注入 开启` / `NR 自动开启: 已就位`
  · （更早）「开 DLSS4 却注入 DLSS5」             ← `mfg` 的开关日志被写成「第一人称」

这三处都不是功能 bug，**但比 bug 更费时间**：日志是排查的第一手材料，
名字错了就等于"用自己的日志把自己带偏"。

本条钉住前两处：
  ① `configure_dlss5_injection()` 写的那条 —— 它写的是 **XXMI 注入库**
     （ReShade 底座 `d3d12.dll` + EFMI `d3d11.dll`），是**所有功能共用的地基**，
     与「DLSS5 神经渲染」那个开关**无关**（关掉那个开关本条照样打印）。
  ② `nr_autostart.arm()` 写的那条 —— 它只是"**挂上监视**"；真正按 NR 键在 `poll()` 里，
     且有 `auto_enable_nr_after_camera_hook` 判据。

⚠️ **判据一律先"去注释"**：这些测试的用意就是"别那么写"，所以实现处的注释里**必然会引用**
   被禁的旧文案 ⇒ 不排除注释就会自己把自己弄红。这个坑 2026-10-07 一天里踩了三次
   （`test_component_toggle_log_labels.py` / `test_asset_expand_idempotent.py` / 本条），
   所以统一用下面这个 `_code_only()`。
"""
from __future__ import annotations

import inspect
import pathlib
import re

from endfieldmodcontroller import launcher, nr_autostart


def _code_only(text: str) -> str:
    """只留**可执行语句** —— 去掉注释**与 docstring**。

    本文件的测试用意是"别那么写"，所以实现处的**注释和文档字符串里必然会引用**被禁的旧文案
    ⇒ 不排除它们就会自己把自己弄红。这个坑 2026-10-07 一天里踩了四次：
      `test_component_toggle_log_labels.py`（注释）、`test_asset_expand_idempotent.py`（注释）、
      本条（先注释、后 docstring）。
    ⇒ **根治办法是用 AST**：解析后删掉每个作用域开头的字符串表达式（docstring），
      再 `ast.unparse()` 回来 —— 注释本来就不在 AST 里。
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(text))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def test_injection_log_does_not_say_dlss5():
    """★ 注入库那条日志不能自称"DLSS5 注入"（它其实是共用底座）。"""
    src = _code_only(inspect.getsource(launcher.configure_dlss5_injection))
    assert "DLSS5 注入" not in src, "又把共用底座写成『DLSS5 注入』了（会让人以为与 DLSS5 开关有关）"
    assert "注入库" in src, "日志里应当出现『注入库』这个词"


def test_injection_log_names_the_shared_base():
    """★ 文案要能看出它写的是"ReShade 底座 + EFMI"这套共用地基。"""
    src = _code_only(inspect.getsource(launcher.configure_dlss5_injection))
    assert "ReShade 底座" in src and "EFMI" in src, "没有写清注入库是什么"
    assert "DLSS4" in src or "共用" in src, "没有说明它服务于哪些功能"


def test_nr_arm_log_says_watching_not_pressing():
    """★ `arm()` 那条要说"**挂上监视**"，不能让人以为已经在按 NR 键了。"""
    src = _code_only(inspect.getsource(nr_autostart.arm))
    assert "已就位" not in src, "又写成『已就位』了（用户会以为它已经在按键）"
    assert "监视" in src, "应当写清只是挂上监视"


def test_nr_arm_reflects_the_switch():
    """★ `arm()` 的文案要**照当前开关**说实话（关着就说不会按键）。"""
    src = _code_only(inspect.getsource(nr_autostart.arm))
    assert "auto_enable_nr_after_camera_hook" in src, "文案没有反映开关状态"
    assert "不会按键" in src or "已关闭" in src, "关掉时应当明说不会按键"


def test_real_press_still_guarded_by_switch():
    """★ 反向确认：真正按键那一步（`poll`）**仍然**受开关约束（别为了文案把判据删了）。"""
    src = pathlib.Path(nr_autostart.__file__).read_text(encoding="utf-8")
    poll = src[src.index("def poll("):]
    tail = poll.find("\ndef ")
    poll = poll[: tail if tail != -1 else len(poll)]
    assert "auto_enable_nr_after_camera_hook" in poll, "poll 里的开关判据不见了（会导致关掉 DLSS5 仍去按键）"
    assert re.search(r"send_key\(", poll), "poll 里没有按键动作了？测试需要同步"
