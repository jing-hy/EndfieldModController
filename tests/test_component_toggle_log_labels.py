"""开关日志的文案必须**逐组件写全**（2026-10-07）。

**为什么值得钉住**：原写法是
```python
f"{'DLSS5' if component == 'dlss5' else '第一人称'} 插件{'启用' if enabled else '停用'}"
```
⇒ **`mfg`（DLSS4 多帧生成）被打印成「第一人称」**。

代价是实测过的：现场日志那一段的真实语义是
```
09:58:34  DLSS5 插件启用（移动 0）
09:58:34  DLSS5 插件停用（移动 3）      ← 开 DLSS4 ⇒ 互斥关 DLSS5
09:58:34  第一人称 插件停用（移动 1）    ← 这条其实是 **DLSS4 被启用**
09:58:34  DLSS5 插件启用（移动 3）      ← 又开 DLSS5 ⇒ 互斥关 DLSS4
```
按字面读会得出"第一人称被停用"，**把判断带偏**（我自己就在这上面绕了一圈）。
⇒ 日志是排查的第一手材料，**名字错了等于判据被污染**。
"""
from __future__ import annotations

import inspect
import pathlib
import re

from endfieldmodcontroller import api as api_module

SOURCE = pathlib.Path(api_module.__file__).read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """只保留代码行（去掉整行注释），避免"注释里引用旧写法"把判据弄红。"""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return out


def test_no_hardcoded_else_branch_in_code():
    """★ 代码里不许再有"否则就是第一人称"的三元表达式（注释里引用旧写法不算）。"""
    code = "\n".join(_code_lines(SOURCE))
    assert "'DLSS5' if component == 'dlss5' else '第一人称'" not in code, \
        "那个把 mfg 写成第一人称的三元表达式又回到代码里了"


def test_label_table_covers_three_components():
    """★★ 必须有一张把三个组件名分开的表，且 `mfg` 的名字看得出是 DLSS4。"""
    match = re.search(r"_component_label\s*=\s*\{(?P<body>[^}]*)\}", SOURCE, re.S)
    assert match, "找不到组件名映射表（_component_label）"
    pairs = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', match.group("body")))
    assert set(pairs) >= {"dlss5", "firstperson", "mfg"}, f"表里缺组件：{pairs}"
    labels = list(pairs.values())
    assert len(set(labels)) == len(labels), f"名字有重复，日志里仍分不清：{pairs}"
    assert "第一人称" not in pairs["mfg"], f"mfg 又被写成第一人称：{pairs['mfg']}"
    assert "DLSS4" in pairs["mfg"], f"mfg 的名字应当能看出是 DLSS4：{pairs['mfg']}"


def test_toggle_log_uses_the_label_variable():
    """开关日志那一行必须用上那个变量，而不是又写回三元表达式。"""
    src = inspect.getsource(api_module.EndfieldModControllerApi.set_component_addon)
    assert "_component_label" in src, "开关日志没用组件名映射"
    assert "{_component_label} 插件" in src, "日志格式变了，请同步这条测试"
    # 互斥两条分支的按钮名字也要能看出是哪个组件
    assert "DLSS4 多帧生成" in src and "DLSS5 神经渲染" in src, "互斥提示里的组件名不全"
