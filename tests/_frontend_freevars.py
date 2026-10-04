"""前端「自由标识符」检查的**唯一实现**（供 `tests/test_frontend_freevars.py` 使用）。

抓的是这一类事故（本项目已真实发生 6 次，与历史 `modDownloadFinished is not defined` 同型）：

* `<script setup>` 里调用了**没有 import、也没有定义**的名字
  —— `computed(...)`、`showAlert(...)`、`showProgressToast(...)`、`sleep(...)`…
  后果是"点下去什么都没发生"：控制台报一句 ReferenceError，被 catch 吞掉或直接中断函数，
  界面上看起来只是"操作没做成"；
* `store.xxx(...)` —— `store` 是纯数据（reactive）对象，上面**没有任何方法**，
  调用它等于必然抛 `TypeError`。

为什么现有测试没抓到：`tests/test_frontend_components.py` 只检查"模板里用到的组件是否 import"，
而这些名字出现在**脚本块**里，且 `npm run build` 对未声明的标识符**不报错**
（打包器把它当全局变量，运行时才炸）。

实现注意（踩过的坑）：**必须先剥掉注释与字符串字面量**，否则注释里的 `get_state()`
与 CSS 里的 `var(--x)` 会变成成片的误报；箭头函数参数要用禁止嵌套括号的正则，
否则会从最外层 `(` 开始吞掉一大段代码。
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"

# JS 全局 / 语言关键字 / Vue 编译器宏：出现在任何地方都合法
GLOBALS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "new", "await", "function",
    "else", "do", "super", "this", "case", "delete", "void", "yield", "throw", "in", "of",
    "true", "false", "null", "undefined", "NaN", "Infinity", "async", "class", "try", "finally",
    "window", "document", "console", "navigator", "location", "history", "localStorage",
    "sessionStorage", "alert", "confirm", "prompt", "performance", "globalThis", "self", "top",
    "Math", "JSON", "Object", "Array", "String", "Number", "Boolean", "Promise", "Map", "Set",
    "WeakMap", "WeakSet", "Symbol", "BigInt", "Proxy", "Reflect", "Date", "RegExp", "Error",
    "TypeError", "RangeError", "SyntaxError", "URL", "URLSearchParams", "Blob", "File", "FileReader",
    "FormData", "Headers", "Request", "Response", "AbortController", "TextEncoder", "TextDecoder",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent", "decodeURIComponent",
    "encodeURI", "decodeURI", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "queueMicrotask", "structuredClone",
    "atob", "btoa", "fetch", "Intl", "Float32Array", "Uint8Array",
    "MutationObserver", "IntersectionObserver", "ResizeObserver", "import", "var", "let", "const",
    # Vue 编译器宏（`<script setup>` 里不需要 import）
    "defineProps", "defineEmits", "defineExpose", "defineOptions", "defineSlots",
    "defineModel", "withDefaults", "useTemplateRef",
}

DECL_PATTERNS = [
    re.compile(r"import\s+(?:([\w$]+)\s*,\s*)?(?:\{([^}]*)\}|\*\s+as\s+([\w$]+)|([\w$]+))\s+from"),
    re.compile(r"import\s*\(\s*[\"']"),                      # 动态 import
    re.compile(r"\b(?:const|let|var)\s+([^;=\n]+)"),
    re.compile(r"\bfunction\s+([\w$]+)\s*\("),
    re.compile(r"\bclass\s+([\w$]+)"),
    re.compile(r"\(([^()]*)\)\s*(?:=>|\{)"),                  # 箭头函数/函数参数（禁嵌套）
    re.compile(r"\bfunction\s*[\w$]*\s*\(([^)]*)\)"),
    re.compile(r"\bcatch\s*\(\s*([\w$]+)"),
    re.compile(r"\bfor\s*\(\s*(?:const|let|var)\s+([^)]*?)\s+(?:in|of)\s"),
]
IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
# 作为函数被调用（前面不是 `.` 或标识符字符 → 排除 obj.foo() ）
CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
# `store.<name>(` —— store 是 reactive 数据对象，当前**没有**任何方法
STORE_CALL_RE = re.compile(r"(?<![\w$])store\s*\.\s*([\w$]+)\s*\(")
STORE_FUNCS: set[str] = set()


def strip_noise(script: str) -> str:
    """去掉注释与字符串字面量（否则注释里的 `get_state()`、CSS 的 `var(--x)` 全是误报）。"""
    text = re.sub(r"/\*[\s\S]*?\*/", " ", script)
    text = re.sub(r"(^|[^:'\"\\])//[^\n]*", r"\1 ", text, flags=re.M)
    text = re.sub(r"`(?:\\.|[^`\\])*`", " `` ", text)
    text = re.sub(r"\"(?:\\.|[^\"\\\n])*\"", ' "" ', text)
    text = re.sub(r"'(?:\\.|[^'\\\n])*'", " '' ", text)
    return text


def script_of(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix != ".vue":
        return strip_noise(text)
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", text, re.S)
    return strip_noise("\n".join(blocks))


def _names_from_fragment(fragment: str) -> set[str]:
    """`a, {b, c: d}, e = 1, ...rest` → {a, b, d, e, rest}"""
    out: set[str] = set()
    text = re.sub(r"\{([^{}]*)\}", lambda m: " " + m.group(1) + " ", fragment)
    for ch in "[]()":
        text = text.replace(ch, " ")
    for chunk in text.split(","):
        piece = chunk.strip().lstrip(".")
        if ":" in piece:
            piece = piece.split(":", 1)[0]
        if "=" in piece:
            piece = piece.split("=", 1)[0]
        piece = piece.strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", piece):
            out.add(piece)
    return out


def declared_names(script: str) -> set[str]:
    names: set[str] = set()
    for index, pattern in enumerate(DECL_PATTERNS):
        for match in pattern.finditer(script):
            if index == 0:                      # import 语句
                for group in (g for g in match.groups() if g):
                    if "/" in group or group.endswith((".js", ".vue")):
                        continue
                    names.update(IDENT_RE.findall(group))
            else:
                for group in (g for g in match.groups() if g):
                    names.update(_names_from_fragment(group))
    for match in re.finditer(r"import\s*\{([^}]*)\}\s*from", script):
        for piece in match.group(1).split(","):
            piece = piece.strip()
            if not piece:
                continue
            piece = piece.split(" as ")[-1].strip() if " as " in piece else piece
            if re.fullmatch(r"[A-Za-z_$][\w$]*", piece):
                names.add(piece)
    return names


def check_script(script: str, label: str = "script") -> list[str]:
    """检查一段脚本文本，返回问题列表（供测试与自检共用）。"""
    text = strip_noise(script)
    declared = declared_names(text) | GLOBALS
    problems: list[str] = []
    for match in CALL_RE.finditer(text):
        name = match.group(1)
        if name in declared:
            continue
        line = text[: match.start()].count("\n") + 1
        problems.append(f"{label}:~{line} 调用了未声明的 `{name}(`")
    for match in STORE_CALL_RE.finditer(text):
        name = match.group(1)
        if name in STORE_FUNCS:
            continue
        line = text[: match.start()].count("\n") + 1
        problems.append(f"{label}:~{line} 调用了 `store.{name}(` —— store 上没有这个方法")
    return problems


def frontend_files() -> list[Path]:
    files = sorted(list(SRC.rglob("*.vue")) + list(SRC.rglob("*.js")))
    return [p for p in files if "node_modules" not in p.parts]


def check_all() -> list[str]:
    problems: list[str] = []
    for path in frontend_files():
        problems.extend(check_script(script_of(path), str(path.relative_to(SRC.parent.parent))))
    return problems
