"""模板里用到的组件**必须 import**（2026-10-03 抓到的真因）。

**事故**：`ModLibraryPage.vue` 的模板里一直写着
`<CharacterAssignDialog ref="assignRef" />`，**却从没 import 过它**。
Vue 于是把这个标签当成"未知自定义元素"：
* 页面上什么都不渲染（弹窗永远出不来）；
* `assignRef.value` 拿到的是个 **DOM 元素**（`<characterassigndialog>`）而不是组件实例，
  调 `assignRef.value.openFor(...)` 抛
  `TypeError: l.value.openFor is not a function`（CDP 实测抓到），又被当场的 catch 吞掉。

用户看到的就是「Mod 的更多里点更改角色归属**没反应**」。辅助页（`AssistPage.vue`）有 import，
所以那边一直是好的 —— 典型的"两个页面只有一份写对了"。

**为什么构建不报**：生产构建对未解析组件**静默跳过**（只有 dev 模式才 warn
`Failed to resolve component`），`vite build` 照样成功。所以只能靠这条静态检查钉住。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "frontend" / "src"

# 原生标签 + Vue 内置标签：这些不需要 import
NATIVE = {
    "html", "head", "body", "base", "link", "meta", "style", "title", "script", "noscript",
    "div", "span", "p", "a", "img", "br", "hr", "b", "i", "u", "s", "em", "strong", "small",
    "sub", "sup", "code", "pre", "kbd", "samp", "var", "mark", "abbr", "cite", "q", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
    "form", "label", "input", "textarea", "button", "select", "option", "optgroup", "datalist",
    "output", "progress", "meter", "fieldset", "legend", "details", "summary", "dialog",
    "video", "audio", "source", "track", "canvas", "map", "area", "iframe", "embed", "object",
    "param", "picture", "svg", "path", "circle", "rect", "line", "polyline", "polygon", "g",
    "defs", "use", "symbol", "text", "tspan", "clippath", "mask", "pattern", "lineargradient",
    "radialgradient", "stop", "filter", "fegaussianblur", "ellipse",
    # HTML5 语义标签（漏一个就会误报，第一次跑就踩了 section / aside 这两个）
    "section", "article", "aside", "header", "footer", "main", "nav", "hgroup", "address",
    "time", "wbr", "ruby", "rt", "rp", "bdi", "bdo", "data", "dfn", "ins", "del", "menu", "search",
    # Vue 内置
    "template", "slot", "component", "transition", "transitiongroup", "keepalive",
    "teleport", "suspense",
}

TAG_RE = re.compile(r"<([A-Za-z][A-Za-z0-9-]*)(?=[\s/>])")
IMPORT_RE = re.compile(r"^import\s+([A-Za-z_$][\w$]*)\s+from\s+[\"'](.+?)[\"']", re.MULTILINE)
# 命名导入也要算：`import { Check, ImageOff } from "lucide-vue-next"`、`import { A as B } from …`
NAMED_IMPORT_RE = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*[\"'](.+?)[\"']", re.MULTILINE)
LOCAL_COMPONENT_RE = re.compile(r"^(?:const|let|var)\s+([A-Z][\w$]*)\s*=", re.MULTILINE)


def _files() -> list[Path]:
    return sorted(SRC.rglob("*.vue"))


def _analyze(path: Path) -> set[str]:
    """返回这个 .vue 里**用了但没导入**的组件名。"""
    src = path.read_text(encoding="utf-8")
    head, _, _ = src.rpartition("</template>")
    template = head.rpartition("<template>")[2]
    script = src.split("</script>", 1)[0]

    used = set()
    for raw in TAG_RE.findall(template):
        name = raw.replace("-", "").lower()
        if name in NATIVE:
            continue
        # kebab-case（`setting-switch`）在 <script setup> 里也能自动匹配 PascalCase 的导入
        used.add("".join(part[:1].upper() + part[1:] for part in raw.split("-") if part))

    available = {match[0] for match in IMPORT_RE.findall(script)}
    for names, _module in NAMED_IMPORT_RE.findall(script):
        for part in names.split(","):
            part = part.strip()
            if part:
                available.add(part.split(" as ")[-1].strip())
    available |= {match[0] for match in LOCAL_COMPONENT_RE.findall(script)}
    return {name for name in used if name not in available}


def test_no_unimported_components() -> None:
    """★ 模板里出现的每个组件标签，都必须在 `<script setup>` 里 import（或本地定义）。"""
    bad: list[str] = []
    for path in _files():
        missing = _analyze(path)
        if missing:
            bad.append(f"{path.relative_to(SRC.parent.parent)}: {sorted(missing)}")
    assert not bad, (
        "模板用了没导入的组件 —— Vue 会把它当未知自定义元素（页面上什么都不渲染，"
        "ref 拿到的是 DOM 元素、调方法直接 TypeError）：\n  " + "\n  ".join(bad)
    )


def test_the_checker_would_catch_the_real_bug(tmp_path: Path) -> None:
    """自检：这条防线**确实能**抓出当初那个 bug（否则它是摆设）。"""
    broken = tmp_path / "Broken.vue"
    broken.write_text(
        "<script setup>\nimport Card from './Card.vue';\n</script>\n"
        "<template>\n  <Card />\n  <CharacterAssignDialog ref=\"assignRef\" />\n</template>\n",
        encoding="utf-8",
    )
    assert _analyze(broken) == {"CharacterAssignDialog"}


@pytest.mark.parametrize("name", ["ModLibraryPage.vue", "AssistPage.vue"])
def test_assign_dialog_is_imported(name: str) -> None:
    """两个页面都得真的导入那个「归类」弹窗（服装页当初就是漏了这一行）。"""
    src = (SRC / "pages" / name).read_text(encoding="utf-8")
    assert re.search(r"^import\s+CharacterAssignDialog\s+from\s+[\"'].*CharacterAssignDialog\.vue[\"']",
                     src, re.MULTILINE), f"{name} 没有 import CharacterAssignDialog"
