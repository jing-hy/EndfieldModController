"""PE 依赖预检：找出"某个 DLL/EXE 依赖、但在本机解析不到"的那些 DLL。

**为什么要它**（2026-10-05）：issue #16 那台机器上游戏以 `0xC0000135 STATUS_DLL_NOT_FOUND`
退出（用户描述："滴滴两声、任务栏只闪一下终末地图标、没有窗口"），而**诊断包里只能看出
"游戏极早期就失败了"，看不出到底缺哪个 DLL** —— 让一个自称"电脑小白"的反馈者去装
Process Monitor / 开 loader snaps 不现实。

本模块在**游戏启动之前**把「我们要注入的 DLL + 游戏 exe + 游戏目录里已有的 proxy」的
**PE 静态导入表**读出来（纯标准库，不需要 `pefile`），逐个查依赖能否在
「游戏目录 → System32 → SysWOW64」里解析到，把**解析不到的**列出来。

**判据与限制**（会原样写进诊断包，避免被当成"全量体检"）：
* 只查**静态导入表**；延迟加载（delay-load）与运行期 `LoadLibrary` 拿不到 ——
  所以"没报缺"**不等于**"运行期不缺"；
* 只做**文件名级**解析（同名即算找到），不比对版本与位数；
* `api-ms-win-*` / `ext-ms-*` 是**API set 虚拟名**（System32 下没有同名文件），一律跳过；
* 纯只读，单文件毫秒级。
"""
from __future__ import annotations

import struct
from pathlib import Path

# 这些前缀是 API set 虚拟名，不是磁盘上的文件 —— 查它们只会得到假阳性
_API_SET_PREFIXES = ("api-ms-win-", "ext-ms-win-", "api-ms-onecoreuap-")

_KNOWN_MACHINE = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}


def _pe_headers(data: bytes) -> tuple[int, int, int, int] | None:
    """返回 `(coff, size_opt, opt, nsec)`；不是合法 PE 就 None。"""
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    try:
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
            return None
        coff = e_lfanew + 4
        nsec = struct.unpack_from("<H", data, coff + 2)[0]
        size_opt = struct.unpack_from("<H", data, coff + 16)[0]
        opt = coff + 20
    except struct.error:
        return None
    return coff, size_opt, opt, nsec


def pe_machine(path: Path) -> str:
    """目标架构（`x64` / `x86` / `arm64`；读不出返回空串）。"""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    headers = _pe_headers(data)
    if headers is None:
        return ""
    coff = headers[0]
    try:
        return _KNOWN_MACHINE.get(struct.unpack_from("<H", data, coff)[0], "")
    except struct.error:
        return ""


def pe_imports(path: Path) -> list[str]:
    """PE 静态导入表里的 DLL 名（保序去重）。不是 PE / 读不到 → 空列表。"""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    headers = _pe_headers(data)
    if headers is None:
        return []
    _coff, size_opt, opt, nsec = headers
    try:
        magic = struct.unpack_from("<H", data, opt)[0]
    except struct.error:
        return []
    # 数据目录起点：PE32+ 是 opt+112，PE32 是 opt+96；第 1 项就是导入表
    dd = opt + (112 if magic == 0x20B else 96)
    try:
        import_rva = struct.unpack_from("<I", data, dd + 8)[0]
    except struct.error:
        return []
    if not import_rva:
        return []

    sections: list[tuple[int, int, int, int]] = []
    base = opt + size_opt
    for index in range(nsec):
        entry = base + index * 40
        try:
            vsize = struct.unpack_from("<I", data, entry + 8)[0]
            vaddr = struct.unpack_from("<I", data, entry + 12)[0]
            rsize = struct.unpack_from("<I", data, entry + 16)[0]
            raw = struct.unpack_from("<I", data, entry + 20)[0]
        except struct.error:
            break
        sections.append((vaddr, max(vsize, rsize), raw, rsize))

    def rva_to_offset(rva: int) -> int | None:
        for vaddr, span, raw, _rsize in sections:
            if vaddr <= rva < vaddr + span:
                return raw + (rva - vaddr)
        return None

    names: list[str] = []
    offset = rva_to_offset(import_rva)
    while offset:
        try:
            name_rva = struct.unpack_from("<I", data, offset + 12)[0]
        except struct.error:
            break
        if not name_rva:
            break
        name_off = rva_to_offset(name_rva)
        if name_off is None:
            break
        try:
            end = data.index(b"\0", name_off)
        except ValueError:
            break
        name = data[name_off:end].decode("ascii", "replace")
        if name and name not in names:
            names.append(name)
        offset += 20
    return names


def default_search_dirs(game_dir: Path | None = None) -> list[Path]:
    """依赖解析目录（**顺序即 Windows 的搜索顺序**：exe 所在目录优先）。"""
    dirs: list[Path] = []
    if game_dir is not None:
        dirs.append(Path(game_dir))
    import os

    system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    dirs.append(system_root / "System32")
    dirs.append(system_root / "SysWOW64")
    dirs.append(system_root)
    return dirs


def is_api_set(name: str) -> bool:
    return name.lower().startswith(_API_SET_PREFIXES)


def resolve_dependency(name: str, dirs: list[Path]) -> Path | None:
    """按给定目录顺序找这个依赖（**同名即算找到**，不比对版本）。"""
    for directory in dirs:
        try:
            candidate = directory / name
        except TypeError:
            continue
        if candidate.is_file():
            return candidate
    return None


def check_paths(
    paths: list[Path],
    *,
    game_dir: Path | None = None,
    extra_dirs: list[Path] | None = None,
    search_dirs: list[Path] | None = None,
) -> dict:
    """逐条查这些 PE 文件的依赖能不能解析到。

    返回 `{"checked": [...], "missing": [{file, machine, dep, searched}], "skipped": [...]}`。
    `missing` 里的每一项就是"**这个文件依赖它、但本机哪儿都找不到**"。

    `search_dirs` 给了就**只用它**（测试与特殊场景用）；否则用
    `default_search_dirs(game_dir)` 再叠加 `extra_dirs`。
    """
    if search_dirs is not None:
        dirs = [Path(item) for item in search_dirs]
    else:
        dirs = default_search_dirs(game_dir)
        if extra_dirs:
            dirs = dirs + [Path(item) for item in extra_dirs]
    checked: list[str] = []
    skipped: list[dict] = []
    missing: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        if is_api_set(path.name):
            # 输入**本身**就是 API set 的 stub（游戏目录里常见一堆 `api-ms-win-*.dll`）——
            # 它们不是真 DLL，拿去解析只会刷出满屏"没有导入表"的噪音。
            continue
        machine = pe_machine(path)
        if not machine:
            skipped.append({"file": str(path), "reason": "不是 PE 文件或读不出来"})
            continue
        deps = pe_imports(path)
        if not deps:
            skipped.append({"file": str(path), "reason": "没有静态导入表（或解析失败）"})
            continue
        checked.append(str(path))
        for dep in deps:
            if is_api_set(dep):
                continue
            if resolve_dependency(dep, dirs) is None:
                missing.append({
                    "file": str(path),
                    "machine": machine,
                    "dep": dep,
                    "searched": [str(item) for item in dirs],
                })
    return {"checked": checked, "missing": missing, "skipped": skipped}


def report_lines(result: dict, *, limit: int = 20) -> list[str]:
    """把 `check_paths` 的结果渲染成诊断包里的几行（**判据与限制一并写出来**）。"""
    checked = result.get("checked") or []
    missing = result.get("missing") or []
    skipped = result.get("skipped") or []
    lines = [
        "-- 注入 DLL 依赖检查（PE 静态导入表）",
        f"   检查了 {len(checked)} 个可解析的 PE 文件"
        f"（要注入的 DLL / 游戏 exe / 游戏目录里已有的 proxy）",
    ]
    if not checked:
        lines.append("   （没有可检查的文件）")
    if missing:
        lines.append(f"   !! 有 {len(missing)} 个依赖在本机解析不到 —— 这类缺失会让进程"
                     f"以 `0xC0000135 STATUS_DLL_NOT_FOUND` 极早期退出：")
        for item in missing[:limit]:
            lines.append(f"      · {Path(item['file']).name}（{item.get('machine') or '?'}）"
                         f" 需要 {item['dep']}")
        if len(missing) > limit:
            lines.append(f"      …另有 {len(missing) - limit} 条")
    else:
        lines.append("   OK  静态导入表上的依赖都能解析到")
    for item in skipped[:8]:
        lines.append(f"   -- 跳过 {Path(item['file']).name}：{item['reason']}")
    lines.append("   注：只覆盖**静态导入表**。延迟加载与运行期 `LoadLibrary` 拉起的 DLL 不在其中，"
                 "所以「没报缺」不等于运行期不缺；解析是**文件名级**（不比对版本/位数）。")
    lines.append("   这段是给 `0xC0000135 STATUS_DLL_NOT_FOUND`（游戏或注入器**极早期**就退出）"
                 "用的：真缺 DLL 时，上面会直接点名缺的是哪一个。")
    return lines
