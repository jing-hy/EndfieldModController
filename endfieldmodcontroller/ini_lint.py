"""按 3DMigoto 源码规则体检生成的 `controller.ini` —— 找出会被**静默跳过**的行。

**为什么需要它**（2026-10-01）：面板"按键不生效"排了十几轮，最后靠读源码找到三处静默失败点，
而它们全都**只在游戏里运行时才表现为"某个功能没反应"**，从文本上根本看不出来：

1. **`[Constants]` 段**（`IniHandler.cpp::ParseConstantsSection`）—— 每行 `global [persist] $name = value`：
   * 变量名必须过 `valid_variable_name`（`CommandList.cpp`）：以 `$` 开头、**第 2 个字符必须是小写字母或 `_`**、
     之后**只允许小写字母/数字/`_`**（大写、连字符等一律非法）；
   * 初值必须能被 `swscanf_s(L"%f%n")` **完整**吃掉（`len != val->length()` 即失败）—— 例如带中文单位、
     带多余字符、空值以外的怪东西都会失败；
   * **同名不得重复声明**（`Redeclaration`）。
   **三种失败都只是 `continue`（不 erase）** —— 那行于是**留在段里**，在第二遍"把 `[Constants]` 当命令列表解析"时
   被当成命令，可能连带影响整段。
2. **`[CommandList*]` 段里的 `$var = value`**（`CommandListOperand::parse`）—— 解析顺序是
   浮点 → ini param → **变量**；**左值/右值变量都必须是已声明的全局/局部变量**，否则该行会被当成非法命令丢弃。
3. **`[Key*]` 段**的 `key =` —— 每个 token 必须是合法的 VK（`vkeys.h` 表 + `no_` 前缀），
   且 `run =` 指向的段必须存在（`input.cpp::RegisterKeyBinding` 解析失败会整体放弃该绑定）。

用法：`python -m endfieldmodcontroller.ini_lint <controller.ini>`（或直接调 `lint_file`）。
"""
from __future__ import annotations

import re
from pathlib import Path

# vkeys.h::VKMappings 的键名（小写）+ 常见别名；另支持 VK_ 前缀
VK_NAMES = {
    "lbutton", "rbutton", "cancel", "mbutton", "xbutton1", "xbutton2", "back", "backspace",
    "back_space", "tab", "clear", "return", "enter", "shift", "control", "ctrl", "menu", "alt",
    "pause", "capital", "caps", "capslock", "caps_lock", "escape", "space", "prior", "pgup",
    "pageup", "page_up", "next", "pgdn", "pagedown", "page_down", "end", "home", "left", "up",
    "right", "down", "select", "print", "execute", "snapshot", "prscr", "printscreen",
    "print_screen", "insert", "delete", "help", "lwin", "left_win", "left_windows", "rwin",
    "right_win", "right_windows", "apps", "sleep", "multiply", "add", "separator", "subtract",
    "decimal", "divide",
}
VK_NAMES |= {f"numpad{i}" for i in range(10)}
VK_NAMES |= {f"f{i}" for i in range(1, 25)}
VK_NAMES |= set("abcdefghijklmnopqrstuvwxyz") | set("0123456789")
MODIFIER_WORDS = {"no_modifiers", "no_ctrl", "no_alt", "no_shift", "no_lwin", "no_rwin",
                  "no_control", "ctrl", "alt", "shift", "control", "lctrl", "rctrl", "lalt",
                  "ralt", "lshift", "rshift", "lwin", "rwin"}
# 变量名：**只要求以 `$` 开头、不含空白**。
# ⚠️ 曾经按"源码规则"写成 `^\$[a-z_][a-z0-9_]*$`（全小写、不含反斜杠），结果在本仓库实测里
# **全是误报**：Mod 生态大量使用驼峰名（`$backSkirt`）与带路径的跨命名空间名
# （`$\EFMIv1\required_version`，EFMI 官方模板就这么写）—— 而且它们**都能正常工作**。
# 会误报的检查器只会训练人去忽略它（比没有更糟），所以放宽到这条几乎不可能误报的判据。
VALID_NAME_RE = re.compile(r"^\$\S+$")


def valid_variable_name(name: str) -> bool:
    """与 3DMigoto `CommandList.cpp::valid_variable_name` 等价。"""
    return bool(VALID_NAME_RE.match(name))


def _const_value_ok(value: str) -> tuple[bool, str]:
    """模拟 `swscanf_s(L"%f%n")` 的"必须完整吃掉"语义。"""
    v = value.strip()
    if not v:
        return True, ""            # 空值合法（等价于不写初值）
    try:
        # C 的 %f 比 Python float() 宽松（允许 1e5 / .5 / 1. 等），这里按宽松侧允许
        float(v)
        return True, ""
    except ValueError:
        return False, f"初值无法按 %f 解析: {v!r}"


def lint_text(text: str) -> list[str]:
    problems: list[str] = []
    section = ""
    declared: set[str] = set()
    key_sections: dict[str, list[str]] = {}
    command_sections: set[str] = set()
    pending: dict[str, list[str]] = {}

    lines = text.splitlines()
    for idx, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            low = section.lower()
            if low.startswith("commandlist"):
                command_sections.add(section)
            elif low.startswith("key"):
                pending.setdefault(section, [])
            continue

        if section.lower() == "constants":
            m = re.match(r"^(global\s+)?(persist\s+)?(\$\S+)\s*(?:=\s*(.*))?$", line, re.IGNORECASE)
            if m:
                name, value = m.group(3), (m.group(4) or "")
                if not valid_variable_name(name):
                    problems.append(f"{idx}: [Constants] 变量名非法（会被静默跳过）: {name}")
                if name in declared:
                    problems.append(f"{idx}: [Constants] 重复声明（会被静默跳过）: {name}")
                declared.add(name)
                ok, why = _const_value_ok(value)
                if not ok:
                    problems.append(f"{idx}: [Constants] {name} —— {why}")
            continue

        low_sec = section.lower()
        if low_sec.startswith("key"):
            if line.lower().startswith("key") and "=" in line:
                value = line.split("=", 1)[1].strip()
                for token in value.split():
                    t = token.lower()
                    if t in MODIFIER_WORDS:
                        continue
                    base = t[3:] if t.startswith("vk_") else t
                    if base.startswith("no_"):
                        base = base[3:]
                    if base and base[0] == "$":
                        problems.append(f"{idx}: [{section}] key 里用了变量（不支持）: {token}")
                    elif base not in VK_NAMES:
                        problems.append(f"{idx}: [{section}] 无法识别的键名（该绑定会被整体放弃）: {token}")
            elif line.lower().startswith("run") and "=" in line:
                target = line.split("=", 1)[1].strip()
                pending.setdefault(section, []).append(target)
            continue

        if low_sec.startswith("commandlist") or section.lower() == "present":
            # 变量赋值：**只报"赋给未声明的本文件变量"**（这才是真正会被丢弃的情形）。
            # ⚠️ 两个必须放过的形态（初版误报了 25 处）：
            #   ① 右值可以是**表达式**（`$mc_input * 10 + 1`）—— 3DMigoto 支持算术；
            #   ② 左值可以是**跨命名空间引用**（`$\mods\MC_xxx\0.ini\coat`）—— 指向别的 ini 的变量。
            m = re.match(r"^(\$[^\s=]+)\s*=\s*(.+)$", line)
            if m:
                lhs, rhs = m.group(1), m.group(2).strip()
                namespaced = lhs.startswith("$\\") or "\\" in lhs
                if not namespaced:
                    if not valid_variable_name(lhs):
                        problems.append(f"{idx}: [{section}] 赋值左值名字非法: {lhs}")
                    elif lhs not in declared:
                        problems.append(f"{idx}: [{section}] 赋值给**未声明**的变量（该行会被丢弃）: {lhs}")
                for tok in re.findall(r"\$[A-Za-z_][A-Za-z0-9_]*", rhs):
                    if tok not in declared:
                        problems.append(f"{idx}: [{section}] 右值变量**未声明**（该行会被丢弃）: {tok}")

    # run = 目标段是否存在（含命名空间前缀写法）
    for sec, targets in pending.items():
        for target in targets:
            plain = target.split("\\")[-1]
            if plain not in command_sections and f"commandlist{plain}".lower() not in {
                s.lower() for s in command_sections
            }:
                # 允许 CommandList\EFMIv1\XXX 这种外部引用，只在名字像本文件的时报
                if not target.count("\\"):
                    problems.append(f"[{sec}] run 指向不存在的 CommandList: {target}")
    return problems


def lint_file(path: Path) -> list[str]:
    return lint_text(path.read_text(encoding="utf-8", errors="replace"))


if __name__ == "__main__":
    import sys

    # 中文 Windows 控制台默认 GBK，下面的 ✅ / ❌ 会直接把它撞崩（UnicodeEncodeError），
    # 于是"体检通过"反而看起来像失败（exit=1）。2026-10-02 修。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\zmdmod\modtest\runtime\builtin\XXMI\EFMI\Mods\MC_Controller\controller.ini")
    found = lint_file(target)
    print(f"体检: {target}\n  行数={len(target.read_text(encoding='utf-8', errors='replace').splitlines())}")
    if not found:
        print("  ✅ 未发现会被 3DMigoto 静默跳过的行")
    else:
        print(f"  ❌ 发现 {len(found)} 处问题：")
        for item in found:
            print("   -", item)
