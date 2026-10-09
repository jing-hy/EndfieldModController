"""注释/文案审计（2026-10-07 用户要求：「跑一下全量注释和文案审计处理，不要留过时的和误导的」）。

**本文件钉住审计中真正改掉的 4 处**，避免回归：

① `launcher.configure_dlss5_injection()` 的函数名带 `dlss5`，但它管的是**共用注入底座**
   （`d3d12.dll` + `EFMI\\d11.dll`，DLSS4 / DLSS5 / 第一人称 / 面板全靠它）——
   文档串必须写清这一点，否则会再有人问「为什么我没开 dlss5 日志也说按 dlss5」；
② 同一个函数里那条**用户可见的 action 文案**不能再自称 "DLSS5 注入关闭"；
③ `api.py` 里注入库开关失败时的日志同理；
④ `initialize.py` 调 `_check_dlss5_nrstyle` 前的注释**不能说"自动改回 0"** ——
   那个自动改动早就按用户要求删了，实际**只报告不改动**（注释与行为相反会误导排查）。

⚠️ 判据一律先过 `_code_only()`（AST 剥注释 + docstring）—— 这些改动的注释里**必然会引用**
   被禁的旧文案，不排除就会自己把自己弄红（同族坑 2026-10-07 踩过四次）。
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import re
import textwrap

from endfieldmodcontroller import api as api_module
from endfieldmodcontroller import initialize, launcher


def _code_only(text: str) -> str:
    """只留可执行语句；剥掉注释与 docstring。"""
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


# ── ① 共用底座不许被文档串写成"DLSS5 注入" ─────────────────────────────────
def test_injection_docstring_names_the_shared_base():
    doc = inspect.getdoc(launcher.configure_dlss5_injection) or ""
    assert "共用" in doc or "底座" in doc, "文档串没写清它管的是共用注入底座"
    for name in ("第一人称", "面板"):
        assert name in doc, f"文档串没说明它也服务于 {name}"
    # ⚠️ 只看"有没有提到共用底座"是不够的（正文里提一句、首行仍自称 DLSS5 注入也能过）——
    #    反向验证时就是这么漏掉的。所以**首行也不许**用 DLSS5 命名这件事。
    first_line = doc.strip().splitlines()[0]
    assert "DLSS5 注入" not in first_line, f"文档串首行仍自称『DLSS5 注入』：{first_line!r}"


def test_injection_action_copy_not_blamed_on_dlss5():
    """★ 用户可见的 action 文案不许再自称「DLSS5 注入关闭」。

    ⚠️ 这句**不在 `configure_dlss5_injection` 里**（我第一版就断错了函数 ⇒ 反向验证抓不住）——
    它在 `ensure_injections()`（2026-10-07 审计时实测确认），所以按**整个模块的代码行**扫。
    """
    src = pathlib.Path(launcher.__file__).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "DLSS5 注入关闭" not in code, "用户可见的 action 文案又自称『DLSS5 注入关闭』了"
    assert "注入库已清空" in code, "应当写成『注入库已清空』"


def test_that_target_function_still_exists():
    """钉住上面那条测试的前提：「XXMI 注入库已清空」确实在 `ensure_injections` 里。"""
    src = pathlib.Path(launcher.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    target = next(i for i, l in enumerate(lines, 1) if "XXMI 注入库已清空" in l)
    owner = next(
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= target <= (node.end_lineno or node.lineno)
    )
    assert owner == "ensure_injections", f"那句话换函数了（现在在 {owner}）—— 请同步上面的测试"


def test_api_error_log_not_blamed_on_dlss5():
    """`api.py` 里注入库开关失败时的日志也不能自称 DLSS5。"""
    src = pathlib.Path(api_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "DLSS5 注入开关失败" not in code, "日志又把共用底座说成『DLSS5 注入』了"
    assert "注入库开关失败" in code


# ── ② NRStyle 那条：注释不许承诺"自动改回" ──────────────────────────────────
def test_nrstyle_comment_does_not_promise_auto_fix():
    """★ 注释不能承诺「自动改回 0」—— 那个动作早已删除，实际只报告。"""
    src = pathlib.Path(initialize.__file__).read_text(encoding="utf-8")
    # 找到"调用 _check_dlss5_nrstyle"那一行，看它**紧邻的上方注释**
    lines = src.splitlines()
    call_idx = next(i for i, l in enumerate(lines) if "_check_dlss5_nrstyle(config, report, log)" in l and "def " not in l)
    above: list[str] = []
    j = call_idx - 1
    while j >= 0 and lines[j].lstrip().startswith("#"):
        above.insert(0, lines[j])
        j -= 1
    blob = " ".join(above)
    assert above, "那条调用上方应当有注释说明它是做什么的"
    assert "只报告" in blob or "不改动" in blob, f"注释没写清『只报告不改动』：{blob[:120]}"
    # 允许在"说明历史"里提到自动改回，但必须同时否定它
    if "自动改回" in blob:
        assert ("早就" in blob or "原来" in blob or "更正" in blob or "删" in blob), \
            "提到『自动改回』时必须同时说明它已被删除，否则就是过时注释"


def test_nrstyle_checker_really_does_not_modify():
    """★ 反向确认：`_check_dlss5_nrstyle` 确实不改文件（注释与行为一致）。"""
    src = _code_only(inspect.getsource(initialize._check_dlss5_nrstyle))
    for bad in ("write_text", ".save(", "unlink", "rename", "shutil.", "setattr"):
        assert bad not in src, f"这个函数里出现了写动作 {bad!r}，与『只报告』的说明矛盾"


# ── ③ 审计结论本身：那两类"疑似过时"其实是现行 ─────────────────────────────
def test_hotkey_lock_is_still_current():
    """★ 锁 Mod 原键与 F13..F24 协议**都是现行**（审计时曾被我的错误印象判成过时）。

    这条钉住"别再有人把它们当废弃机制清理掉"。
    """
    from endfieldmodcontroller import core

    assert core.HOTKEY_LOCK_ENABLED is True, "锁键动作被关掉了？那是现行功能，不是废弃代码"
    assert re.fullmatch(r"VK_F\d+", core.LOCKED_MOD_HOTKEY), \
        f"锁键用的键变了：{core.LOCKED_MOD_HOTKEY}（F13..F24 是面板内部通道）"
