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
    # 本机可用的 RTX 卡与其 CUDA 架构（按 sm 升序）—— "用哪份 DLSS5 运行库"的唯一来源。
    # 下游（runtime_assets / initialize / api / 依赖页）都读这三个字段，别各算一套。
    cards = rtx_cards(info["adapters"])
    info["dlss5_cards"] = [{"name": name, "sm": sm} for name, sm in cards]
    info["dlss5_sm"] = cards[-1][1] if cards else None
    info["dlss5_variant"] = dlss5_runtime_variant(info["dlss5_sm"])
    info["dlss_verdict"] = _verdict(names)
    _CACHE = info
    return info


def dlss5_supported(refresh: bool = False) -> tuple[bool, str, str]:
    """这台机器能不能用 **DLSS5 神经渲染**？返回 `(supported, gpu_name, reason)`。

    **判据（2026-10-05 重定，此前是"只支持 RTX 50 系"）**：NVIDIA 且型号名含 `RTX`
    （= 有 tensor core）⇒ **RTX 20 系及以上都支持**。

    为什么能放开：DLSS5 的神经渲染代码跑在 `nvngx_dlssnr.dll` 里，而那份运行库是
    **按 CUDA 架构分别编译**的 —— NVIDIA 官方那份只带 `sm_120`（Blackwell），
    社区把它重定向到了 `sm_89` / `sm_86` / `sm_75`（实测 fatbin 记录，见
    `runtime_assets` 的变体表）。所以 40/30/20 系**不再需要等官方放开**，
    只要用对架构的那一份运行库即可。

    **不支持的**：没有 NVIDIA 卡（AMD / Intel / 核显 / 无独显 —— 没有可用的 NVIDIA
    运行库）、NVIDIA 但非 RTX（GTX 10 系及以下）、以及 **GTX 16 系**：它虽然是 Turing
    `sm_75`，但**没有 tensor core**（型号名里没有 RTX），上游实测"GTX、RTX 16 跑不了"。

    这个函数是判据的唯一实现 —— config 默认值迁移、开关闸门、自检三处都调它。
    """
    try:
        info = collect(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        return True, "", f"读不到设备信息（{exc}）—— 先按支持处理"
    adapters = info.get("adapters") or []
    nvidia = [str(a.get("name") or "") for a in adapters if "nvidia" in str(a.get("name", "")).lower()]
    gpu = "、".join(nvidia) or "未检测到 NVIDIA 显卡"
    if not nvidia:
        return False, gpu, (
            "未检测到 NVIDIA 显卡（AMD / Intel / 核显 / 无独显）—— DLSS5 神经渲染要跑在 "
            "NVIDIA 的运行库里，这类机器上没有可用的运行库，属于硬件不支持、不是装坏了"
        )
    # ⚠️⚠️ **必须逐张卡判，取最高的一张**（2026-10-04 修，用户收到的反馈）：
    # 「双显卡（一张 5080，一张 4060）会被 dlss5 的开关挡住，显示只支持 50 显卡」。
    # 原来是把所有卡名**拼成一串**再 `re.search` 第一个 `rtx\d{4}` —— 取到哪张**完全看
    # 适配器枚举顺序**，装了 5080 的机器会被判成"只有 40 系"、开关直接被挡掉。
    # 正确语义：**只要有一张满足就够了**（用户当然会用那张跑游戏）。
    # 判据收敛到 `rtx_cards()` 一处（"名含 RTX = 有 tensor core"），
    # 支持判定与"用哪份运行库"共用它，避免两处各写一套。
    per_card = rtx_cards(adapters)
    if not per_card:
        return False, gpu, (
            f"检测到 NVIDIA 显卡但**不是 RTX 系列**（{gpu}，GTX 10 系及以下 / GTX 16 系 / MX 等）"
            f"—— DLSS5 神经渲染需要 tensor core（RTX 20 系及以上才有），属于硬件不支持"
        )
    best_name, best_sm = max(per_card, key=lambda item: item[1])
    variant = dlss5_runtime_variant(best_sm)
    if len(per_card) > 1:
        listing = "、".join(f"{name}（{_sm_label(sm)}）" for name, sm in per_card)
        return True, gpu, (
            f"检测到多张显卡：{listing} —— 其中 **{best_name}** 满足 DLSS5 的硬件前提，"
            f"**请让游戏用这张卡跑**（另一张的架构没有对应运行库，不是装坏了）")
    return True, gpu, f"{_sm_label(best_sm)}（有 tensor core，满足 DLSS5 的硬件前提；运行库变体：{variant}）"


# ---------------------------------------------------------------------------
# 显卡 → CUDA 架构（sm）：决定用哪一份 DLSS5 神经渲染运行库
# ---------------------------------------------------------------------------
# 依据（2026-10-05 实测三份运行库的 fatbin 记录，明细则见 runtime_assets 的变体表）：
#   official `310.8.0`       → sm_120 ×30
#   rtx40    `310.8.0-RTX40` → sm_89 ×15 + sm_120 ×30
#   sf       `310.8.SF-v2`   → sm_75 ×15 + sm_86 ×15 + sm_89 ×15 + sm_120 ×23
_SM_BY_RTX_SERIES = {20: 75, 30: 86, 40: 89, 50: 120}
_SERIES_BY_SM = {75: 20, 86: 30, 89: 40, 120: 50}
_GTX16_SM = 75      # GTX 16 系是 Turing sm_75，但**没有 tensor core** ⇒ DLSS5 跑不了


def _sm_label(sm: int) -> str:
    """`sm_89` → `RTX 40 系（sm_89）`，用于给用户看的判词。"""
    series = _SERIES_BY_SM.get(sm)
    return f"RTX {series} 系（sm_{sm}）" if series else f"sm_{sm}"


def nvidia_sm(name_lower: str) -> int | None:
    """显卡名 → CUDA 架构号（sm）。**只回答"架构是多少"，不回答"能不能用"。**

    ⚠️ **GTX 16 系同样返回 75** —— 它是 Turing，但**没有 tensor core**，DLSS5 用不了。
    "能不能用"的唯一判据在 `dlss5_supported()`（那里额外要求型号名里含 `RTX`）；
    本函数只服务于"该给它哪一份运行库"。
    """
    import re

    n = name_lower
    # ① 名字里直接写了 Ada 的工作站卡：`RTX 2000 Ada` / `RTX 5000 Ada` → sm_89
    #    （它的型号数字是 2000/5000，**不能**当成 RTX 20/50 系，见上游同款处理）
    if re.search(r"\bada\b", n) and re.search(r"rtx\s*\d{3,4}", n):
        return 89
    # ② Ampere 工作站：`RTX A2000` - `RTX A6000` → sm_86
    if re.search(r"rtx\s*a\d{3,4}\b", n):
        return 86
    # ③ `Quadro RTX 3000-8000` / `TITAN RTX`（Turing）→ sm_75
    if re.search(r"(quadro\s+rtx|titan\s+rtx)", n):
        return 75
    # ④ 消费级：按型号数字的前两位取代次
    match = re.search(r"(?:rtx|gtx)\s*(\d{3,4})", n)
    if not match:
        return None
    series = int(match.group(1)[:2])
    if series in _SM_BY_RTX_SERIES:
        return _SM_BY_RTX_SERIES[series]
    if series == 16:
        return _GTX16_SM
    return None


def rtx_cards(adapters: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """筛出**有 tensor core 的 NVIDIA 卡**，返回 `[(卡名, sm)]`，按 sm 从低到高。

    "名里含 `RTX`" 就是"有 tensor core"的判据 —— GTX 16 系（sm_75）与 GTX 10 系因此被排除。
    支持判定与"用哪份运行库"共用这一个入口，避免两处各写一套。
    """
    cards: list[tuple[str, int]] = []
    for adapter in adapters:
        name = str(adapter.get("name") or "")
        low = name.lower()
        if "nvidia" not in low or "rtx" not in low:
            continue
        sm = nvidia_sm(low)
        if sm is not None:
            cards.append((name, sm))
    return sorted(cards, key=lambda item: item[1])


# ★★ 「DLSS4 多帧生成」在**本作**上无效 —— 2026-10-07 用户定案，选了"默认禁用 + 写明原因"。
#
# **定案依据（三条互相印证，缺一条都不敢下这个结论）**：
#   ① 终末地**只有 DX11 启动模式**（没有 DX12 模式；DX11 下虽然会加载 d3d12 —— D3D11On12，
#      但那不等于"游戏用原生 D3D12 跑"，而 addon 要的正是后者）；
#   ② **游戏内没有调倍率的接口**（用户原话）⇒ 游戏**从不向 Streamline 提交帧生成请求**；
#   ③ addon 侧实测**完全就绪**：`rewrote 2 arch gate(s) (0x1b0 -> 0x190)`、
#      `full Blackwell framework kernels applied`、`verified mapped DLSS-G provider candidate
#      version 310.9.1.0`、`observed Streamline DLSS-G wrapper version 2.14.1.0` ——
#      而 ReShade 日志里 **一次 `Game request observed` 都没有**，面板 `MFG: Not observed`、
#      `Frame Generation: Game/provider controlled`（不是 `Active`）⇒ **没有请求可接**。
#
# ⇒ 这个开关在本作上属于"看起来能用、实际永远没效果"，正是用户最反感的那种形态
#   （「那些滑块要真的有用，不要就做表面功夫」）⇒ **默认禁用，并把原因写在界面上**。
#
# ⚠️ **复活方式**：以后若终末地加入帧生成，把下面这个常量改回 `False` 即可 ——
#    原有的按显卡判据（40 系放行 / 50 系"能用但提升不大" / 其余锁）**原样保留、一字未删**，
#    改回后立刻恢复原行为（`tests/test_mfg_unlock_scope.py` 钉住了这条路径没有腐烂）。
MFG_UNLOCK_DISABLED_FOR_THIS_GAME = True
MFG_UNLOCK_DISABLED_REASON = (
    "终末地游戏内没有帧生成接口（它只有 DX11 启动模式），所以这个解锁在本作不会生效 —— "
    "程序与驱动这一侧都正常，是游戏本身不提供帧生成。"
)


def mfg_unlock_supported(refresh: bool = False) -> tuple[bool, str]:
    """这台机器能不能用「**DLSS4 多帧生成解锁**」（**只放 40 系**）。

    用户 2026-10-06 定："50 系和其他用不了的锁"。判据（复用既有的 `rtx_cards()` 唯一入口，
    按 **CUDA 架构**判而不是按名字猜）：
      * **`sm_89`（RTX 40 系）⇒ 放行** —— 它被挡住纯粹是软件架构白名单
        （`nvngx_dlssg.dll` 里与 `0x1b0`(Blackwell) 比架构 id），解锁后能从 2x 提到 3x/4x；
      * **`sm_120`（RTX 50 系）⇒ 锁** —— 官方本来就有多帧生成（6X 只给 50 系），
        不需要这个 hack；
      * **30/20 系、GTX、A 卡、核显 ⇒ 锁** —— 连 Ada 的插值内核都没有，解锁也没意义。

    返回 `(能用吗, 给用户看的一句话)`。多卡机器取"**最高代次**"（与 `dlss5_supported` 同一口径）。

    ⚠️ **本作当前恒返回不可用**（见文件上方 `MFG_UNLOCK_DISABLED_FOR_THIS_GAME` 的三条定案依据）。
    下面那套按显卡的判据**完整保留**，`MFG_UNLOCK_DISABLED_FOR_THIS_GAME = False` 即恢复。
    """
    if MFG_UNLOCK_DISABLED_FOR_THIS_GAME:
        return False, MFG_UNLOCK_DISABLED_REASON
    try:
        info = collect(refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        return False, f"读不到设备信息（{exc}）—— 先按不支持处理"
    per_card = rtx_cards(info.get("adapters") or [])
    if not per_card:
        return False, "没有可用的 NVIDIA RTX 显卡 —— 这个功能需要有 tensor core 的 NVIDIA 卡。"
    # ⚠️ **取最高代次**（与 `dlss5_supported` 同一口径）：双卡机器（比如一张 4060 +
    #    一张 5080）用户会用**最强那张**跑游戏 ⇒ 判据要按"最高的那张"来算。
    top = max(sm for _name, sm in per_card)
    if top == 89:
        return True, ("检测到 RTX 40 系显卡 —— 这一档被挡在 2x 是软件白名单造成的，"
                      "解锁后可以开到 3x/4x（本作官方上限是 4X）。")
    if top >= 100:
        # ★ **50 系解锁开放**（2026-10-06 用户要求）：「那说明 50 系也能用，你可以把 50 系的锁
        #   关掉，但是对 50 系说明提升不大」。有 50 系用户的面板截图证实：这个 addon 在 50 系上
        #   能正常加载（页签出现、DLSS-G 被识别），所以不必锁着 —— 只是**收益有限**，如实说明。
        return True, ("检测到 RTX 50 系显卡 —— 它本身就有官方多帧生成（本作上限 4X 是官方档位），"
                      "所以**这个解锁对它的提升不大**：能用，但通常看不出差别。想试可以开。")
    return False, (f"检测到 RTX {top} 架构的显卡 —— 这个解锁是给 40 系（Ada）准备的，"
                   f"这一档没有相应的插值内核，开了也不会有帧生成。")


def dlss5_runtime_variant(sm: int | None) -> str:
    """sm → **首选**的 DLSS5 运行库变体（`official` / `rtx40` / `sf`）。

    只是首选：真正用哪一份还要看文件在不在位、以及它的 fatbin 里有没有本机架构，
    见 `runtime_assets.select_dlssnr_variant()`。
    """
    if sm is None:
        return ""
    if sm >= 120:
        return "official"     # NVIDIA 官方 FP8 版，Blackwell 满速
    if sm == 89:
        return "rtx40"        # 社区针对 Ada 重定向的版本；没下到就回落 sf
    if sm in (75, 86):
        return "sf"           # 社区 FP16 路径版（20/30 系）
    return ""


def best_rtx_sm(refresh: bool = False) -> int | None:
    """本机可用的**最高 CUDA 架构**（None = 这张机器用不了 DLSS5）。

    **"该用哪份运行库"的唯一入口**：一律从 `collect()` 的 `adapters` **现算**，
    不读它那几个派生字段（`dlss5_sm` 等）—— 派生字段只给诊断包展示用。
    这样打桩（只给 `adapters`）与真实运行会得到同一个结论，不会出现
    "配置迁移认得出 40 系、运行库选择却认成不支持"这种自相矛盾。
    """
    try:
        info = collect(refresh=refresh)
    except Exception:  # noqa: BLE001 - 读不到设备信息就按"不支持"处理（调用方会说明）
        return None
    cards = rtx_cards(info.get("adapters") or [])
    return cards[-1][1] if cards else None


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

    2026-10-01 加。⚠️ 判"DLSS5 能不能用"**不要用这个函数** —— 只用"代次"会把
    GTX 16 系（Turing，无 tensor core）也当成能用。唯一判据是 `dlss5_supported()`。

    ⚠️ 它**只认第一个匹配**，只适合"传进来的就是一张卡"的场合。要看多卡请用
    `nvidia_generations()`（多卡）或 `rtx_cards()`（逐卡带架构。
    """
    found = nvidia_generations(names_lower)
    return found[0] if found else None


def _verdict(names_lower: str) -> str:
    """给"DLSS5 能不能用"一个一眼可读的结论（诊断包 summary 用）。

    只讲**硬件前提 + 该用哪份运行库**，不是硬判定 —— 具体还得看运行库指纹与游戏面板里的
    `成功NR帧`。判据与 `dlss5_supported()` 完全一致：**名含 RTX（有 tensor core）+ 取架构最高的一张**。
    """
    segments = [seg.strip() for seg in names_lower.split(" / ") if seg.strip()]
    rtx_segments = [seg for seg in segments if "nvidia" in seg and "rtx" in seg]
    cards = [(seg, nvidia_sm(seg)) for seg in rtx_segments]
    known = [(name, sm) for name, sm in cards if sm is not None]
    if not known:
        if rtx_segments:
            return ("检测到 RTX 显卡但**读不出架构**（型号串里没有可识别的数字）→ 请以游戏面板的"
                    "「成功NR帧」为准，并把诊断包发我们（`deviceinfo` 需要补一条型号规则）")
        if any("nvidia" in seg for seg in segments):
            return ("检测到 NVIDIA 显卡但**不是 RTX 系列**（GTX 10 系及以下 / GTX 16 系 / MX 等）"
                    "→ 这些卡没有 tensor core，DLSS5 神经渲染跑不起来（硬件不支持，不是配置问题）")
        return ("**未检测到 NVIDIA 显卡**（AMD / Intel / 核显 / 无独显）→ DLSS5 神经渲染在此机器上"
                "无法启用，属于硬件不支持、不是配置问题")
    known.sort(key=lambda item: item[1])
    listing = "、".join(f"{name}（{_sm_label(sm)}）" for name, sm in known)
    best_sm = known[-1][1]
    variant = dlss5_runtime_variant(best_sm)
    if len(known) > 1:
        return (f"检测到多张可用显卡：{listing} → **按架构最高的那张（{_sm_label(best_sm)}）** 准备"
                f"运行库（变体 `{variant}`）；请让游戏用这张卡跑")
    return (f"检测到 {_sm_label(best_sm)} → 具备 DLSS5 神经渲染的硬件前提"
            f"（运行库变体：`{variant}`；若实际不出帧，看诊断包的「运行库指纹」段）")


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
    sm = info.get("dlss5_sm")
    if sm:
        cards = info.get("dlss5_cards") or []
        listing = "、".join(f"{item.get('name')}=sm_{item.get('sm')}" for item in cards)
        lines.append(
            f"DLSS5 运行库: 本机架构 **sm_{sm}** → 变体 `{info.get('dlss5_variant') or '?'}`"
            f"（探测到的可用卡：{listing}）"
        )
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
