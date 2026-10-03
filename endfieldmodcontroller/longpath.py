r"""Windows 长路径（>260）支持：能用就用，用不上就给出可照做的指引。

背景（issue #12 实测）：一个 Mod 的目录名本身就 68 个字符，加上三层嵌套，
最终路径 **264 字符**，超过 Windows 的 MAX_PATH 上限（259 可用）⇒
父目录建得出来、最后那个文件写不进去 ⇒ `[Errno 2] No such file or directory`。

这里提供两件事：
* :func:`extended` —— 给路径加 `\\?\` 前缀（Win32 API 见到它就跳过 260 检查）；
  **只在 Windows 且确实是绝对路径时加**，其它情况原样返回。
* :func:`check_lengths` —— 解压**之前**预判"哪些条目会超长"，
  好让调用方一次性把话说清楚，而不是解到一半炸一句 errno。
"""
from __future__ import annotations

import os
from pathlib import Path

# Win32 的"扩展长度路径"前缀。加上它，API 就不再做 MAX_PATH 检查。
_PREFIX = "\\\\?\\"
# Windows MAX_PATH 是 260（含结尾 NUL）⇒ 实际可用 259 个字符。
MAX_PATH_CHARS = 259


def extended(path: str | Path) -> str:
    r"""返回带 `\\?\` 前缀的路径（Windows 上才加；已是扩展前缀就不重复加）。

    ⚠️ 只对**绝对路径**有效，且**必须是反斜杠**形式 —— 所以这里会先 `abspath`。
    非 Windows 平台、或路径本身不合法（含 NUL）时**原样返回**，绝不抛异常。
    """
    if os.name != "nt":
        return str(path)
    text = str(path)
    if not text or "\x00" in text:
        return text
    if text.startswith(_PREFIX):
        return text
    # UNC 路径（\\server\share）要写成 \\?\UNC\server\share
    try:
        absolute = os.path.abspath(text)
    except (OSError, ValueError):
        return text
    if absolute.startswith("\\\\"):
        return _PREFIX + "UNC" + absolute[1:]
    return _PREFIX + absolute


def path_length(path: str | Path) -> int:
    """按 Windows 的口径算路径长度（统一成反斜杠、去掉扩展前缀后计）。"""
    text = str(path)
    if text.startswith(_PREFIX):
        text = text[len(_PREFIX):]
    return len(text.replace("/", "\\"))


def is_too_long(path: str | Path, *, limit: int = MAX_PATH_CHARS) -> bool:
    """这条路径会不会超过 Windows 上限。"""
    return path_length(path) > limit


def check_lengths(dest: Path, members, *, limit: int = MAX_PATH_CHARS) -> dict:
    """解压**之前**预判：`dest` 下解出 `members` 会不会有超长路径。

    `members` 是压缩包里的条目名（可带 `/` 分隔的中间目录）。
    返回 `{"too_long": [...], "worst": int, "limit": int, "dest_len": int}`；
    调用方据此**一次性讲清楚**，而不是解到一半抛 errno。
    """
    dest_len = path_length(dest)
    worst = dest_len
    too_long: list[tuple[str, int]] = []
    for member in members:
        name = str(member).replace("/", "\\").replace("\\\\", "\\")
        total = dest_len + 1 + len(name)
        if total > worst:
            worst = total
        if total > limit:
            too_long.append((str(member), total))
    too_long.sort(key=lambda item: -item[1])
    return {"too_long": too_long, "worst": worst, "limit": limit, "dest_len": dest_len}


def explain(dest: Path, verdict: dict, *, extra: str = "") -> str:
    r"""把预判结果变成一段**用户能照做**的中文说明。"""
    too_long = verdict.get("too_long") or []
    limit = int(verdict.get("limit") or MAX_PATH_CHARS)
    worst = int(verdict.get("worst") or 0)
    lines = [
        f"这个压缩包解开后会有 {len(too_long)} 个文件路径超过 Windows 的长度上限"
        f"（{limit} 字符，最长会到 {worst} 字符）。",
        "",
        "**为什么会失败**：Windows 默认不允许超过 260 字符的路径，"
        "所以目录能建出来、最后那个文件却写不进去，报的就是 "
        "`No such file or directory`。",
        "",
        f"**解压目标**：{dest}（这一段本身就有 {verdict.get('dest_len')} 字符）",
        "",
        "**最长的几个**：",
    ]
    for name, total in too_long[:5]:
        lines.append(f"  {total} 字符  {name}")
    if len(too_long) > 5:
        lines.append(f"  …另有 {len(too_long) - 5} 个")
    lines += [
        "",
        "**怎么办（任选其一）**：",
        "  · 把 Mod 库换到更短的路径（例如 `D:\\Mods`），再重新导入 —— 这是最省事的；",
        "  · 或者手动解压：把包解开后，**先给最外层文件夹改成短名字**（比如 `zfy`），"
        "再把里面的内容放进 Mod 库；",
        "  · 或者开启 Windows 的长路径支持（需要改系统设置）。",
    ]
    if extra:
        lines += ["", extra]
    return "\n".join(lines)
