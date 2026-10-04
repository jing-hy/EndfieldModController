"""设备信息（CPU / 内存 / 系统 / 显卡与驱动）—— 给诊断包和崩溃包用。

**为什么要它（用户 2026-10-01 要求）**：「下一版本要在日志包中包含用户设备型号，
判断是不是显卡不支持」。此前诊断包里只有"游戏目录、组件版本、注入链"，一旦反馈
"DLSS5 不出帧 / 花屏 / 进来就崩"，我们无法判断是**他的机器本来就不支持**（没有 N 卡、
GTX 老卡、显存太小、驱动太旧），还是我们这边配置错了 —— 只能来回问。

**实现约束**：
* 只读**注册表 + ctypes**，**不起任何子进程**（`wmic`/`powershell` 会闪黑窗、还慢，
  而用户明确要求"启动与运行过程中不允许出现任何 cmd 控制台黑窗"）。
* 全部读取都在毫秒级，失败一律降级成 `(读不到)`，绝不抛异常、绝不拖慢打包。
"""
from __future__ import annotations

import ctypes
import os
import platform
from typing import Any

# 显卡类的注册表位置：{4d36e968-...} 是 Windows 的「显示适配器」设备类 GUID。
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
_CPU_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
_WIN_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"

_CACHE: dict[str, Any] | None = None


def _reg_str(root: int, path: str, name: str) -> str:
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
        return str(value).strip()
    except Exception:  # noqa: BLE001 —— 注册表读不到就是读不到，不影响打包
        return ""


def _reg_qword_mb(root: int, path: str, name: str) -> int:
    """读一个可能是 QWORD/二进制形式的"字节数"值，换算成 MB。读不到返回 0。"""
    try:
        import winreg

        with winreg.OpenKey(root, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
    except Exception:  # noqa: BLE001
        return 0
    if isinstance(value, bytes):
        try:
            value = int.from_bytes(value, "little")
        except (TypeError, ValueError):
            return 0
    try:
        size = int(value)
    except (TypeError, ValueError):
        return 0
    # 明显不是字节数（个别驱动会写成 MB 数字）就不换算，避免给出荒谬的显存
    if size <= 0:
        return 0
    return int(round(size / 1048576))


def _total_memory_mb() -> int:
    """物理内存总量（ctypes 调 GlobalMemoryStatusEx，比读注册表准）。"""

    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0
        return int(round(status.ullTotalPhys / 1048576))
    except Exception:  # noqa: BLE001
        return 0


def _adapters() -> list[dict[str, Any]]:
    """枚举显示适配器（名称 / 驱动版本 / 显存）。"""
    import winreg

    found: list[dict[str, Any]] = []
    for index in range(16):
        path = f"{_DISPLAY_CLASS}\\{index:04d}"
        name = _reg_str(winreg.HKEY_LOCAL_MACHINE, path, "DriverDesc")
        if not name:
            continue
        if name.lower().startswith(("microsoft basic", "microsoft hyper-v", "microsoft remote")):
            # 基本显示适配器 / 远程桌面虚拟显卡：不是真实独显，收进来只会误导判断
            continue
        entry = {
            "name": name,
            "driver": _reg_str(winreg.HKEY_LOCAL_MACHINE, path, "DriverVersion"),
            "memory_mb": _reg_qword_mb(winreg.HKEY_LOCAL_MACHINE, path, "HardwareInformation.qwMemorySize")
            or _reg_qword_mb(winreg.HKEY_LOCAL_MACHINE, path, "HardwareInformation.MemorySize"),
        }
        vendor = _reg_str(winreg.HKEY_LOCAL_MACHINE, path, "ProviderName")
        if vendor:
            entry["vendor"] = vendor
        found.append(entry)
    return found


def collect(refresh: bool = False) -> dict[str, Any]:
    """收集一次设备信息（进程内缓存；注册表读取很快，但没必要重复读）。"""
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE

    import winreg

    info: dict[str, Any] = {
        "cpu": _reg_str(winreg.HKEY_LOCAL_MACHINE, _CPU_KEY, "ProcessorNameString"),
        "cpu_cores": os.cpu_count() or 0,
        "memory_mb": _total_memory_mb(),
        "os": platform.platform(),
        "os_name": _reg_str(winreg.HKEY_LOCAL_MACHINE, _WIN_KEY, "ProductName"),
        "os_version": _reg_str(winreg.HKEY_LOCAL_MACHINE, _WIN_KEY, "DisplayVersion"),
        "os_build": _reg_str(winreg.HKEY_LOCAL_MACHINE, _WIN_KEY, "CurrentBuild"),
        "adapters": _adapters(),
    }

    names = " / ".join(a["name"] for a in info["adapters"]).lower()
    nvidia = [a for a in info["adapters"] if "nvidia" in a["name"].lower()]
    info["has_nvidia"] = bool(nvidia)
    info["has_rtx"] = "rtx" in names
    info["has_gtx"] = "gtx" in names
    info["dlss_verdict"] = _verdict(names)
    _CACHE = info
    return info


def dlss5_supported(refresh: bool = False) -> tuple[bool, str, str]:
    """这台机器能不能用 **DLSS5 神经渲染**？

    返回 `(supported, gpu_name, reason)`。判据 = **NVIDIA 显卡代次 ≥ 50 系**（DLSS 5 首发
    RTX 50 独占，40 系官方表态后续支持但当前驱动/运行库尚未放开 —— 实测 40 系机器上
    NGX 会以 `0xBAD00001`（FeatureNotSupported）拒掉 feature 18，见 lesson `0mup6bvc`）。

    2026-10-01 用户要求：「**开启时检测机器，如果不是 50 系就默认关 dlss5，开启 dlss5 的
    时候弹窗说明拒绝**」—— 这个函数就是那个判据的唯一实现，config 默认值迁移、开关闸门、
    自检三处都调它，避免各写一套。
    """
    try:
        info = collect(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        return True, "", f"读不到设备信息（{exc}）—— 先按支持处理"
    adapters = info.get("adapters") or []
    nvidia = [str(a.get("name") or "") for a in adapters if "nvidia" in str(a.get("name", "")).lower()]
    gpu = "、".join(nvidia) or "未检测到 NVIDIA 显卡"
    if not nvidia:
        return False, gpu, "未检测到 NVIDIA 显卡 —— DLSS5 神经渲染无法启用"
    # ⚠️⚠️ **必须逐张卡判代次，取最高的一张**（2026-10-04 修，用户收到的反馈）：
    # 「双显卡（一张 5080，一张 4060）会被 dlss5 的开关挡住，显示只支持 50 显卡」。
    # 原来是把所有卡名**拼成一串**再 `re.search` 第一个 `rtx\d{4}` —— 取到哪张**完全看
    # 适配器枚举顺序**，于是装了 5080 的机器被判成"只有 40 系"、开关直接被挡掉。
    # 正确语义：**只要有一张满足就够了**（用户当然会用那张跑游戏）。
    per_card = [(name, nvidia_generation(name.lower())) for name in nvidia]
    known = [(name, gen) for name, gen in per_card if gen is not None]
    if not known:
        return False, gpu, f"识别不出显卡代次（{gpu}）—— DLSS5 目前只支持 RTX 50 系"
    best_name, best = max(known, key=lambda item: item[1])
    if best >= 50:
        if len(known) > 1:
            listing = "、".join(f"{name}（RTX {gen} 系）" for name, gen in known)
            return True, gpu, (
                f"检测到多张显卡：{listing} —— 其中 **{best_name}** 满足 DLSS5 的硬件前提，"
                f"**请让游戏用这张卡跑**（另一张不支持 DLSS5，不是装坏了）")
        return True, gpu, f"RTX {best} 系（满足 DLSS5 的硬件前提）"
    return (
        False,
        gpu,
        f"RTX {best} 系 —— **DLSS5 神经渲染目前只支持 RTX 50 系**"
        f"（官方已表态后续扩展到 40 系，但当前驱动/运行库尚未放开）。"
        f"这类机器上它一帧也出不来（面板会显示「成功NR帧 0」+ `最新NR NGX结果 0xBAD00001`），"
        f"所以默认帮你关掉、也不再让你白折腾。",
    )


def nvidia_generations(names_lower: str) -> list[int]:
    """从一段（**可能含多张卡**的）文字里认出**所有** RTX 代次，按出现顺序返回。

    ⚠️ 判断"这台机器能不能用 DLSS5"必须用这个 / 或用逐卡结果（2026-10-04，用户收到的反馈：
    双显卡机器「一张 5080 + 一张 4060」被开关挡掉）——`nvidia_generation()` 只取**第一个**
    匹配，拼串时取到哪张完全看适配器枚举顺序。
    """
    import re

    return [int(match.group(1)[:2]) for match in re.finditer(r"rtx\s*(\d{3,4})", names_lower)]


def nvidia_generation(names_lower: str) -> int | None:
    """从显卡名里认出 NVIDIA 的**代次**（`RTX 5080` → 50，`RTX 4060 Laptop GPU` → 40）。

    2026-10-01 加：判断"DLSS5 能不能用"**不能只看是不是 RTX** —— DLSS 5 神经渲染
    首发是 **RTX 50 系（Blackwell）独占**（官方 2026-09-04 定档：[17173 报道](https://news.17173.com/content/09022026/080619827.shtml)），
    RTX 40 系要等 NVIDIA 放开（官方后来确认会扩展：[guru3d](https://www.guru3d.com/story/nvidia-reverses-course-dlss-5-is-now-officially-coming-to-rtx-40series-gpus/)）。
    实测印证：一台 RTX 5080 正常出帧，两台 RTX 40 系笔记本（4060 / 4070 Laptop）
    都是 `feature 18 create failed with 0xbad00001`（NGX FeatureNotSupported）。

    ⚠️ 它**只认第一个匹配**，只适合"传进来的就是一张卡"的场合。判"支持与否"请用
    `nvidia_generations()`（多卡）或 `dlss5_supported()`（逐卡取最高）。
    """
    found = nvidia_generations(names_lower)
    return found[0] if found else None


def _verdict(names_lower: str) -> str:
    """给"DLSS5 能不能用"一个一眼可读的结论。

    只讲**硬件前提**，不是硬判定 —— 具体还得看 nvngx 运行库与面板里的 `成功NR帧`
    （见诊断包的运行库指纹段）。判据按**代次**：DLSS5 首发只支持 RTX 50 系。
    """
    if "rtx" in names_lower:
        # ⚠️ **按"最高的那张卡"判断**（2026-10-04 修）：双显卡机器拼串时只取第一个匹配
        # 会把 5080+4060 的机器说成 40 系，和 `dlss5_supported()` 的结论自相矛盾。
        generations = nvidia_generations(names_lower)
        gen = max(generations) if generations else None
        multi = (f"（本机检测到 {len(generations)} 张 RTX 卡："
                 f"{'、'.join(str(g) + ' 系' for g in generations)}，按最高代次判断）"
                 if len(generations) > 1 else "")
        # ⚠️ 判据要与 `dlss5_supported()` 一致（2026-10-04 修）：那边是 `generation >= 50`
        # （为将来 60/70 系留门），这里原来写死 `gen == 50` ⇒ 未来更高代次的机器会被
        # 开关放行、却在诊断包里读到"首发仅支持 50 系…属于支持范围问题"这种互相矛盾的结论，
        # 看包的人会被同一份总结里的两句话带偏。
        if gen is not None and gen >= 50:
            return f"检测到 RTX {gen} 系显卡{multi} → 具备 DLSS5 神经渲染的硬件前提"
        if gen is not None:
            return (
                f"检测到 RTX {gen} 系显卡{multi} → **DLSS5 神经渲染首发仅支持 RTX 50 系**（官方已表态"
                f"后续扩展到 40 系，但当前驱动/运行库尚未放开）。这类机器进游戏后会看到面板"
                f"「成功NR帧 0」+ `最新NR NGX结果 0xBAD00001`（NGX 明确回「不支持该特性」），"
                f"`ReShade.log` 里是 `feature 18 create failed with 0xbad00001` —— "
                f"**属于支持范围问题，不是装坏了、也不是配置错误**，等 NVIDIA 放开后即可用。"
            )
        return (
            "检测到 RTX 显卡（型号里没读到代次）→ 只有 **RTX 50 系**目前支持 DLSS5 神经渲染；"
            "40 系及更早请以面板「成功NR帧」为准"
        )
    if "nvidia" in names_lower:
        return (
            "检测到 NVIDIA 显卡但**不是 RTX 系列**（GTX/其它）→ DLSS 与 DLSS5 神经渲染无法启用，"
            "这属于硬件不支持，不是配置问题"
        )
    return (
        "**未检测到 NVIDIA 显卡** → DLSS5 神经渲染（以及 DLSS 超分）在此机器上无法启用，"
        "这属于硬件不支持，不是配置问题"
    )


def _gb(mb: int) -> str:
    return f"{mb / 1024:.1f} GB" if mb else "(读不到)"


def summary_lines() -> list[str]:
    """诊断包 summary 里的一段（与其它段同风格）。"""
    info = collect()
    lines = ["", "-- 设备与显卡（判断\"是不是显卡不支持\"看这里）--"]
    cpu = info.get("cpu") or "(读不到)"
    cores = info.get("cpu_cores") or 0
    lines.append(f"CPU        : {cpu}" + (f"（逻辑处理器 {cores} 个）" if cores else ""))
    lines.append(f"内存       : {_gb(int(info.get('memory_mb') or 0))}")
    lines.append(f"系统       : {_os_text(info)}")
    adapters = info.get("adapters") or []
    lines.append(f"显示适配器 : {len(adapters)} 个")
    for index, adapter in enumerate(adapters, 1):
        memory = int(adapter.get("memory_mb") or 0)
        lines.append(
            f"  [{index}] {adapter.get('name')}"
            f" | 驱动 {adapter.get('driver') or '(读不到)'}"
            + (f" | 显存 {_gb(memory)}" if memory else "")
        )
    if not adapters:
        lines.append("  （没读到任何显示适配器）")
    lines.append(f"DLSS5 前提  : {info.get('dlss_verdict')}")
    return lines


def _os_text(info: dict[str, Any]) -> str:
    """`Windows 11 Pro 24H2 (build 26100.7309)` 形式。

    ⚠ 注册表的 `ProductName` 在 **Windows 11 上仍然写着 "Windows 10"**（微软的历史遗留），
    所以按 build 号纠正一次 —— 否则日志包里会写着"Windows 10"而实际是 11，
    排查兼容性问题时会被误导。
    """
    name = str(info.get("os_name") or "").strip()
    version = str(info.get("os_version") or "").strip()
    build = str(info.get("os_build") or "").strip()
    try:
        if build and int(build.split(".")[0]) >= 22000 and name.startswith("Windows 10"):
            name = "Windows 11" + name[len("Windows 10"):]
    except ValueError:
        pass
    text = " ".join(part for part in (name, version) if part).strip() or str(info.get("os") or "")
    return text + (f" (build {build})" if build else "")


def as_text() -> str:
    """崩溃包 `environment.txt` 里的一段。"""
    return "\n".join(line for line in summary_lines() if line != "") + "\n"
