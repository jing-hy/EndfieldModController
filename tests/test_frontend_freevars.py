"""抓「前端脚本块里调用了未声明的名字」这类 bug（2026-10-04 加）。

**为什么需要**：2026-10-04 的全项目审计一次就抓到 **6 处真事故**，全是这个形态 ——
`ConflictDialog.vue` 缺 `computed`（冲突弹窗必炸、可能白屏）、
`SettingPathBrowse.vue` 缺 `showAlert`（设置页所有「浏览…」按钮点了没反应）、
`LaunchPage.vue` 缺 `showProgressToast/hideProgressToast/showToast`（「自动修复完整性」根本不执行）、
`DepsPage.vue` 缺同样三个 + `sleep` 从未定义（抛错被 catch 吞成"操作失败"）、
`SettingsPage.vue` 调了不存在的 `store.refreshState()`（「自动检测」永远没有提示）。
它们与历史事故 `modDownloadFinished is not defined` 完全同型：**控制台报一句、界面上看起来
只是"操作没做成"**，用户完全不知道该报什么。

**为什么现有测试抓不到**：`test_frontend_components.py` 只看"模板里的组件有没有 import"；
`npm run build` 对未声明的标识符**不报错**（打包器当成全局变量，运行时才炸）。

实现见 `tests/_frontend_freevars.py`（唯一实现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _frontend_freevars import check_all, check_script  # noqa: E402


def test_frontend_sources_exist() -> None:
    """前提：前端源码目录必须真的存在（否则下面两条是空跑）。"""
    from _frontend_freevars import frontend_files

    files = frontend_files()
    assert len(files) >= 20, f"只找到 {len(files)} 个前端源文件 —— 路径可能不对"


def test_no_undeclared_calls_in_frontend() -> None:
    """★ 前端的 `<script setup>` 里不许调用"没有 import 也没有定义"的名字。"""
    problems = check_all()
    assert not problems, "前端引用了不存在的名字（运行时会抛 ReferenceError）：\n  " + "\n  ".join(problems)


def test_checker_catches_the_real_bug() -> None:
    """自检：这个防线**确实能**抓出上面那种写法（否则它是摆设）。"""
    sample = (
        "<script setup>\n"
        "import { ref } from \"vue\";\n"
        "import { call } from \"../lib/bridge.js\";\n"
        "const ok = ref(false);\n"
        "async function go() {\n"
        "  // 这一句是坏代码：showAlert 没导入\n"
        "  await showAlert(\"x\", \"y\");\n"
        "  await store.refreshState();\n"
        "  await call(\"get_state\");\n"
        "}\n"
        "</script>\n"
    )
    problems = check_script(sample, "sample")
    assert any("showAlert" in p for p in problems), problems
    assert any("store.refreshState" in p for p in problems), problems
    # 正例：正常写法不该被误报
    good = (
        "<script setup>\n"
        "import { ref, computed, onMounted } from \"vue\";\n"
        "const x = ref(1);\n"
        "const y = computed(() => x.value + 1);\n"
        "onMounted(() => { setTimeout(() => {}, 10); });\n"
        "</script>\n"
    )
    assert check_script(good, "good") == [], check_script(good, "good")
