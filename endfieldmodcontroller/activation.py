"""Activation planning and staging for the PoC.

The library is treated as read-only.  Selected mods are copied into a staging
``Mods`` directory before any INI patch is applied, so original downloads stay
untouched.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import core as mc_core
from . import fsutil

MANAGED_DIR_NAME = "EndfieldModControllerManaged"

# ---------------------------------------------------------------------------
# 「锁 Mod 热键」动作总开关：**唯一来源在 `core.HOTKEY_LOCK_ENABLED`**
# （2026-10-02 停用；为什么停用、怎么复活，那段说明写在 core.py 那里）。
# ⚠ 这里**不做值拷贝**（不写 `HOTKEY_LOCK_ENABLED = mc_core.HOTKEY_LOCK_ENABLED`）——
#   拷贝会让"把开关翻回 True"的复活测试失效（改了 core 的常量，这边还是旧值）。
#   所有判断点一律现读 `mc_core.HOTKEY_LOCK_ENABLED`。
# ---------------------------------------------------------------------------


class LibraryGuardError(RuntimeError):
    """staging 与用户的 **Mod 库** 重叠时抛这个 —— 拒绝执行，宁可什么都不做。

    用户 2026-10-01 硬规则：「任何情况（除用户手动点击移出库外）都不要动用户的 mod 库
    （包括换位置）」。清理 staging 是无条件 `rmtree`，一旦 staging 就是库（或包含库），
    那就是把用户的 Mod 全删掉。调用方（`api.prepare` 等）应当把它转成一句可读的界面提示。
    """


def _log(log: Any, message: str) -> None:
    """可选的回调日志；调用方没给就静默忽略。"""
    if log is None:
        return
    try:
        log(message)
    except Exception:  # noqa: BLE001
        pass


@dataclass
class ActivationReport:
    selected: list[str] = field(default_factory=list)
    dropped: list[dict[str, str]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    # 2026-10-02：依赖**去重与内外优先级**的账 —— 哪些候选被屏蔽了、为什么。
    # 前端/日志靠它说清"你库里有两个 RabbitFX，按'内部优先'只启用了内部那份"。
    dependency_choices: dict[str, str] = field(default_factory=dict)
    blocked_dependencies: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 内部依赖 = 位于 `<库>\_deps\<名字>` 下（控制器自己下载/维护的那一份）
_INTERNAL_DEPS_DIRNAME = "_deps"


def _installed_at(mod: Any) -> int:
    """「最后安装」的判据 = 目录**创建时间**（Windows 上 `st_ctime` 就是创建时间）。

    用户 2026-10-02 要求「如果外部有多个，按最后安装的优先」—— 目录 mtime 会被复制/解压
    工具带着源时间戳改写，创建时间才稳定地反映"这份是什么时候进库的"。
    用**纳秒**（`st_ctime_ns`）：同一批导入的几份可能只差几毫秒，秒级浮点分不出来。
    """
    try:
        st = Path(str(getattr(mod, "path", ""))).stat()
    except OSError:
        return 0
    return int(getattr(st, "st_ctime_ns", 0) or getattr(st, "st_mtime_ns", 0) or 0)


def _is_internal_dependency(mod: Any) -> bool:
    try:
        return Path(str(getattr(mod, "path", ""))).parent.name.lower() == _INTERNAL_DEPS_DIRNAME
    except Exception:  # noqa: BLE001
        return False


def plan_dependencies(
    mods: Iterable[mc_core.ModInfo],
    keys: Iterable[str],
    *,
    prefer_internal: bool = True,
    skip_known_bad: bool = False,
) -> tuple[dict[str, mc_core.ModInfo], list[dict[str, str]]]:
    """为每个"需要的依赖"挑**唯一一份**，其余记成"已屏蔽"。

    用户 2026-10-02 原话：「加个去重，在设置里加个**内部 RabbitFX 优先，默认开**，开的话
    如果还有外部 RabbitFX 就把**外部的屏蔽掉**，没开就把**内部屏蔽掉、就算外部优先**，
    如果**外部有多个，按最后安装的优先**。」
    ⇒ 规则：① 开关决定"内部 / 外部"哪一侧优先；② **优先侧有就只从这一侧取**，另一侧
    整侧屏蔽；③ 同一侧有多份时**只留最后安装的那一份**；④ 优先侧没有才退到另一侧
    （同样只留最后安装的那一份）；⑤ 两侧都没有 → 不在这里决定（调用方按"缺失"报）。
    ⑥ `skip_known_bad`（**2026-10-02 起默认 `False` = 不屏蔽**）：`core.KNOWN_BAD_DEPENDENCIES`
    里的依赖**照常进 staging**。
    **为什么把默认翻转过来**：当初给 RabbitFX 定罪的判据是"它一进 staging，游戏启动几十秒后
    必崩在 `nvgpucomp64`"—— 而那个现场是**我们自己的 bug 造的**：`core.sanitize_ini_control_flow()`
    把 `[ShaderRegex*.Pattern.Replace]` 里**要塞进游戏 shader 的汇编 `endif`** 当成 ini 控制流删掉
    （实测 `RabbitFX.ini`：67 → 5 个 endif，**删了 62 行**），汇编不闭合 ⇒ 驱动编译器当场崩。
    **0.9.2 修掉该 bug 后**，回测显示 staging 产物与库里的源**逐字节一致**（350 个文件 0 差异）。
    ⇒ 按用户准则「**先保留判断机制、停掉动作**」：判据与理由都留在 `KNOWN_BAD_DEPENDENCIES` 里，
    只是不再自动屏蔽。**用户原话：「你把 RabbitFX 加回去，然后让我测试」** —— 等实测确认
    "现在真的不崩"之后再定是永久解除还是恢复屏蔽。
    **要复活（改回屏蔽）**：把这里和 `resolve_active_set` 的默认值改回 `True`
    （或在设置页做成开关）。

    ⚠️ **为什么必须有"只留一份"**：RabbitFX 作者在 GameBanana 页面上写死过
    「Having multiple RabbitFXs will cause unexpected behaviours and game crashes…
    only ever have **one instance**」。
    """
    internal: dict[str, list[mc_core.ModInfo]] = {}
    external: dict[str, list[mc_core.ModInfo]] = {}
    for mod in mods:
        name = str(getattr(mod, "name", ""))
        # **皮肤包不能当依赖候选**（2026-10-02，与 `core.infer_kind_and_group` 同一判据）：
        # 作者会把前置名写进皮肤包名（`laevatain_..._rabbitfx_da62a`），只按名字匹配就会把
        # 它当成"RabbitFX 的一份"—— 一旦 RabbitFX 不再被"已知有害"那道闸拦住，这个 208 MB
        # 的皮肤包就会被当作依赖整个塞进 staging。判据要求"名字像依赖 **且** 没有换装资源"。
        if not mc_core.is_dependency_package(name, Path(str(getattr(mod, "path", "")))):
            continue
        key = mc_core.dependency_key_of(name)
        if not key:
            continue
        (internal if _is_internal_dependency(mod) else external).setdefault(key, []).append(mod)

    chosen: dict[str, mc_core.ModInfo] = {}
    blocked: list[dict[str, str]] = []
    for key in sorted({str(k).lower() for k in keys}):
        if key not in mc_core.DEFAULT_DEPENDENCIES:
            continue                    # 未知依赖：不在这里处理（调用方按 missing 报）
        bad_reason = mc_core.KNOWN_BAD_DEPENDENCIES.get(key) if skip_known_bad else None
        if bad_reason:
            # **已知会崩的依赖：一个变体都不放进 staging**（内外两侧都屏蔽，如实说清原因）
            for mod in list(internal.get(key, [])) + list(external.get(key, [])):
                blocked.append({
                    "name": str(getattr(mod, "name", "")),
                    "path": str(getattr(mod, "path", "")),
                    "key": key,
                    "skipped": "known_bad",
                    "reason": f"已知会导致游戏崩溃，已自动跳过（{bad_reason}）",
                })
            # 库里连一份都没有时，也要留一条"跳过"记录（这样不会被误报成"依赖缺失"）
            if not (internal.get(key) or external.get(key)):
                blocked.append({
                    "name": mc_core.DEFAULT_DEPENDENCIES[key]["display"],
                    "path": "",
                    "key": key,
                    "skipped": "known_bad",
                    "reason": f"已知会导致游戏崩溃，已自动跳过（{bad_reason}）",
                })
            continue
        ins = sorted(internal.get(key, []), key=_installed_at)
        outs = sorted(external.get(key, []), key=_installed_at)
        keep, drop = (ins, outs) if prefer_internal else (outs, ins)
        keep_side, drop_side = ("内部", "外部") if prefer_internal else ("外部", "内部")
        pool = keep or drop
        if not pool:
            continue
        picked = pool[-1]               # 同侧多份 → 最后安装的那份
        chosen[key] = picked
        for mod in pool[:-1]:
            blocked.append({
                "name": str(getattr(mod, "name", "")),
                "path": str(getattr(mod, "path", "")),
                "reason": f"{keep_side}优先：同一侧有多份，只启用最后安装的「{picked.name}」",
            })
        if keep and drop:
            for mod in drop:
                blocked.append({
                    "name": str(getattr(mod, "name", "")),
                    "path": str(getattr(mod, "path", "")),
                    "reason": f"{keep_side}优先：已屏蔽{drop_side}的「{mod.name}」",
                })
    return chosen, blocked


def dependency_note(report: dict[str, Any]) -> list[str]:
    """把"依赖用了哪一份、屏蔽了哪几份、缺了谁"翻译成给人看的日志行。

    用户 2026-10-02 要求依赖去重 + 内外优先级；做完必须**说出来** —— 否则界面上只是
    "少了一个 Mod"，用户无从判断是被屏蔽了还是丢了。
    """
    lines: list[str] = []
    choices = report.get("dependency_choices") or {}
    if choices:
        lines.append(
            "依赖启用：" + "；".join(f"{key} → {name}" for key, name in sorted(choices.items()))
        )
    for item in report.get("blocked_dependencies") or []:
        lines.append(f"依赖去重：屏蔽「{item.get('name')}」（{item.get('reason')}）")
    missing = sorted({str(x) for x in (report.get("missing_dependencies") or [])})
    if missing:
        lines.append(
            "依赖缺失：" + "、".join(missing) + "（库里没有；用到它的 Mod 可能显示不正常）"
        )
    return lines


def resolve_active_set(
    mods: Iterable[mc_core.ModInfo],
    selected_ids: Iterable[str] | None = None,
    *,
    allow_same_character: bool = False,
    prefer_internal_dependencies: bool = True,
    # 2026-10-02：默认 `False` = 不再自动屏蔽 `KNOWN_BAD_DEPENDENCIES`（RabbitFX 照常进 staging）。
    # 原因见 `plan_dependencies` 的 ⑥：那次"进 staging 就崩"是我们自己删 shader 汇编 `endif`
    # 造成的，用户在等实测。要恢复屏蔽就把这里改回 `True`。
    skip_known_bad_dependencies: bool = False,
) -> tuple[list[mc_core.ModInfo], ActivationReport]:
    """解析"最终要生效的 Mod 集合"。

    ``allow_same_character=True`` = **关闭同角色互斥**（用户 2026-10-01 要求：「强行关闭
    角色 Mod 互斥…便于部分同角色但不冲突的 mod」）：此时同一个 ``conflict_group`` 下的
    多个 Mod 会**全部保留**，不再只留第一个。默认 False 保持原行为 —— 同角色两个 Mod
    同时生效常会让游戏崩，所以只在用户明确开启时才放行。
    """
    selected_ids = set(selected_ids or [])
    mods = list(mods)
    candidates = [m for m in mods if not m.is_dependency and (not selected_ids or m.id in selected_ids)]

    chosen: dict[str, mc_core.ModInfo] = {}
    report = ActivationReport()
    for mod in candidates:
        key = mod.conflict_group or mod.group or mod.id
        # ⚠️⚠️ **辅助 Mod 里只有「加载页与壁纸」互斥**（2026-10-03 用户明确：
        #     「那个壁纸是互斥的，但是功能类不是，修一下」）。
        # 背景：辅助 Mod 按 `group` 分组显示，而互斥原本是**按 group 一刀切**的 ——
        # 于是四个分组（加载页与壁纸 / 界面功能类 / 工具画质类 / 其它辅助）全变成
        # "同组只能开一个"，而功能类本来就该能叠加（多个 UI/功能增强一起用是常态）。
        # 现在：壁纸类保持互斥（同时开多个壁纸会互相抢同一张界面图），
        # 其它辅助分组改成**各自独立**（用 mod.id 当 key ⇒ 全部保留）。
        if not allow_same_character and getattr(mod, "kind", "") == "assist":
            # ⚠️⚠️ **判据必须看 `mod.group`，不能看 `key`**（2026-10-03 修「壁纸互斥失效」）。
            # 上一版写的是 `if key != WALLPAPER_GROUP: key = mod.id` —— 而 `key` 来自
            # `mod.conflict_group`（辅助 Mod 的值是 `assist:<各自路径>`）⇒
            # **那个比较永远成立** ⇒ 壁纸也被改成 `mod.id` ⇒ **两个壁纸可以同时开**。
            #（用户实测问「壁纸互斥呢」，一看 `conflict_group` 两者各不相同就露馅了。）
            #
            # 现在：**壁纸类（`group == 加载页与壁纸`）统一用一个 key** ⇒ 组内互斥；
            # 其它辅助分组各自独立（用 `mod.id`）⇒ 可以叠加。
            if str(getattr(mod, "group", "") or "") == mc_core.WALLPAPER_GROUP:
                key = mc_core.WALLPAPER_GROUP
            else:
                key = mod.id
        if allow_same_character:
            # 不用「角色」当 key，改用 Mod 自己的 id —— 于是同角色多个都进 chosen。
            key = mod.id
        if key in chosen:
            report.dropped.append({
                "id": mod.id,
                "name": mod.name,
                "conflict_group": key,
                "kept": chosen[key].id,
            })
            continue
        chosen[key] = mod
        report.selected.append(mod.id)

    # 依赖**按需**激活：只启用被选中 Mod 通过 `requires` 真正引用到的依赖（含传递依赖）。
    #
    # 2026-09-27 修正（用户实测「手动放进去的 Mod 没问题，从控制器放进去的就闪退」）：
    # 原先这里是 `dependencies = [m for m in mods if m.is_dependency]` —— 无条件把
    # `_deps` 下的**全部**依赖都 stage 进去，与用户选了什么无关。于是哪怕只选一个
    # 根本不需要依赖的 Mod，也会被动背上会改写游戏 shader 的库（例如 RabbitFX 的
    # `[ShaderRegex*]` 段），游戏直接闪退；而手动放 Mod 时这些依赖并不存在，所以不崩。
    #
    # 2026-10-02 再修（用户当场实测暴露的"下载了不生效"）：
    # ① **判据统一** —— 以前这里只读 `mod.requires`（sidecar 文件，库里几乎没人写），
    #    而"要不要下载这个依赖"那条链路用的是 `collect_required_dependency_names()`
    #    （**会扫 ini 文本**）。两条链路两套判据 ⇒ 依赖下得来、进不去。现在共用同一判据。
    # ② **候选按名字"包含"来找**（`core.dependency_key_of`）—— 用户手动导入的
    #    `（重要前置）RabbitFX v24_3d366` / `RabbitFX -ENDMI-` 用相等匹配永远命不中。
    # ③ **同一依赖只允许一份进 staging**（`plan_dependencies`）—— RabbitFX 作者写死过
    #    "多个实例会导致异常行为与游戏崩溃"；按用户要求"内部优先（默认）/ 外部优先，
    #    同侧多份取最后安装的"。
    needed: dict[str, mc_core.ModInfo] = {}
    blocked: list[dict[str, str]] = []
    # 每个 Mod 只扫一次 ini（`collect_required_dependency_names` 会读它全部 ini 文本）
    cache: dict[str, list[str]] = {}

    def _needs(mod: mc_core.ModInfo) -> list[str]:
        cache_key = str(mod.id)
        if cache_key not in cache:
            cache[cache_key] = mc_core.collect_required_dependency_names([mod])
        return cache[cache_key]

    pending = list(chosen.values())
    for _round in range(4):             # 传递依赖：依赖自己引用的依赖，最多跟四层
        keys = {str(name).lower() for mod in pending for name in _needs(mod)} - set(needed)
        if not keys:
            break
        picked, dropped = plan_dependencies(
            mods, keys,
            prefer_internal=prefer_internal_dependencies,
            skip_known_bad=skip_known_bad_dependencies,
        )
        blocked.extend(dropped)
        pending = []
        for key, dep in picked.items():
            if key in needed:
                continue
            needed[key] = dep
            pending.append(dep)

    report.dependencies = [m.id for m in needed.values()]
    report.dependency_choices = {key: mod.name for key, mod in needed.items()}
    report.blocked_dependencies = blocked
    # 被"已知有害"那道闸**主动跳过**的依赖 key —— 它们**不算"库里没有"**。
    # 2026-10-02：否则日志会自相矛盾（一边说"已自动跳过 RabbitFX"，一边又说
    # "依赖缺失：RabbitFX（库里没有…）"）。
    skipped_keys = {
        str(item.get("key") or "") for item in blocked if item.get("skipped") == "known_bad"
    }

    for mod in list(chosen.values()) + list(needed.values()):
        for name in _needs(mod):
            key = str(name).lower()
            if key in skipped_keys:
                continue
            if key in mc_core.DEFAULT_DEPENDENCIES and key not in needed:
                if name not in report.missing_dependencies:
                    report.missing_dependencies.append(name)

    active = list(needed.values()) + list(chosen.values())
    return active, report


# 控制器自己在 staging 目录里生成的东西 —— 都不算「用户手动放的 Mod」
CONTROLLER_OWNED_NAMES = frozenset({
    "MC_Controller",
    "MC_Probe.ini",
    MANAGED_DIR_NAME,
    "_endfieldmodcontroller_managed",
    "DISABLED",
})


def find_manual_mods(staging_root: Path) -> list[Path]:
    """staging 目录里**不是控制器生成**的目录，即用户手动放进去的 Mod。

    控制器的产物一律带 `MC_` 前缀，或是 `CONTROLLER_OWNED_NAMES` 里的固定名字。
    """
    if not staging_root.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(staging_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name in CONTROLLER_OWNED_NAMES or child.name.startswith("MC_"):
            continue
        out.append(child)
    return out


def _mod_signature(path: Path) -> set[str]:
    """Mod 目录的特征：所有 ini 里声明的 namespace（用于跨目录改名识别同一个 Mod）。"""
    sig: set[str] = set()
    try:
        inis = list(path.rglob("*.ini"))
    except OSError:
        return sig
    for ini in inis:
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("namespace"):
                sig.add(stripped.replace(" ", "").lower())
    return sig


def _same_mod(a: Path, b: Path) -> bool:
    """两个目录是不是同一个 Mod：先比目录名，再比 namespace 特征。"""
    if a.name == b.name:
        return True
    sig_a = _mod_signature(a)
    return bool(sig_a) and sig_a == _mod_signature(b)


def import_manual_mods(config: Any, log: Any = None) -> dict[str, Any]:
    """把手工放进 Mods 目录的 Mod 同步进 Mod 库，并在 UI 里标记为已开启。

    用户需求（原话）：「手动放进去的和库里的进行比对，如果库里已有，就在 UI 中显示
    那个开启，库里没有就把它放到库里，然后显示开启」。

    流程：
      1. 扫描 staging 目录里所有**非控制器生成**的目录（= 手动放的 Mod）；
      2. 逐个与库里的 Mod 比对：先按目录名，再按 namespace 特征（容忍改名）；
      3. **库里已有** → 只把它记进 `selected_mods`（UI 即显示为开启）；
      4. **库里没有** → 复制进 `library/<名字>/`，同样记进 `selected_mods`；
      5. 迁移成功的**手动目录会从 staging 移除** —— 否则控制器随后 stage 出的
         `MC_<角色>_<名字>` 会与它构成「同角色成对」，EFMI 同时加载同角色两个 Mod
         会直接崩游戏（这个坑已经踩过两次）。
    """
    staging_root = config.staging_mods_path
    library_root = config.library_path
    manual = find_manual_mods(staging_root)
    result: dict[str, Any] = {
        "ok": True,
        "found": len(manual),
        "imported": [],
        "matched": [],
        "selected_added": [],
        "actions": [],
        "warnings": [],
    }
    if not manual:
        return result

    library_root.mkdir(parents=True, exist_ok=True)
    known = [p for p in library_root.iterdir() if p.is_dir()]

    for src in manual:
        target = next((p for p in known if _same_mod(src, p)), None)
        if target is None:
            target = library_root / src.name
            if target.exists():
                target = library_root / f"{src.name}_imported"
            try:
                shutil.copytree(src, target)
            except OSError as exc:
                result["warnings"].append(f"复制 {src.name} 进库失败: {exc}")
                _log(log, f"WARN 手动 Mod 入库失败: {src.name} ({exc})")
                continue
            known.append(target)
            result["imported"].append(target.name)
            result["actions"].append(f"收纳手动 Mod「{src.name}」进库")
            _log(log, f"手动 Mod 已收进库: {src.name} -> {target}")
        else:
            result["matched"].append(target.name)
            _log(log, f"手动 Mod 已在库中: {src.name} -> {target.name}")

        # 从 staging 移除手动目录，避免与随后的 MC_ staging 形成同角色成对。
        # ⚠️ 但**绝不**碰用户的 Mod 库：如果这个"手动目录"其实在库里（staging 与库重叠的
        # 错误配置），删它就等于删用户的 Mod —— 直接跳过并说明（用户 2026-10-01 硬规则）。
        guard = fsutil.library_conflict(library_root, src)
        if guard:
            result["warnings"].append(f"保留 {src.name}：{guard}")
            _log(log, f"WARN 不动 Mod 库，保留 {src.name}（{guard}）")
            continue
        try:
            shutil.rmtree(src)
            result["actions"].append(f"从 Mods 移除手动目录「{src.name}」（改由本程序统一 staging）")
        except OSError as exc:
            result["warnings"].append(f"移除手动目录 {src.name} 失败: {exc}")
            _log(log, f"WARN 移除手动目录失败: {src.name} ({exc})")

    # 重新扫描库，把这些 Mod 标记为选中，让 UI 直接显示为开启
    wanted = {n.lower() for n in (result["imported"] + result["matched"])}
    if wanted:
        try:
            mods = mc_core.scan_library(library_root, staging_root)
        except Exception as exc:  # noqa: BLE001
            mods = []
            result["warnings"].append(f"扫描库失败: {exc}")
        selected = list(config.selected_mods or [])
        for mod in mods:
            if mod.name.lower() in wanted and mod.id not in selected:
                selected.append(mod.id)
                result["selected_added"].append(mod.name)
        if result["selected_added"]:
            config.selected_mods = selected
            try:
                config.save()
            except Exception as exc:  # noqa: BLE001
                result["warnings"].append(f"保存配置失败: {exc}")
            _log(log, f"已在界面勾选: {', '.join(result['selected_added'])}")

    result["ok"] = not result["warnings"]
    return result


def _safe_target(staging_root: Path, mod: mc_core.ModInfo) -> Path:
    group = mc_core.safe_name(mod.group)
    name = mc_core.safe_name(mod.name)
    return staging_root / group / name


def apply_default_action_states(user_ini_path: Path, manifest: dict[str, Any]) -> None:
    """Seed a visible default for selected mods when the user has no saved state.

    Many clothing mods start in their original-outfit state until a toggle is
    applied.  If the user has never used the ReShade controller UI, choose one
    sensible clothing action per mod and persist it, so enabling a mod shows a
    result immediately.  Existing per-action state is never overwritten.
    """
    actions = manifest.get("actions") or []
    if not actions:
        return
    controller_ns = mc_core.CONTROLLER_NAMESPACE

    def bad(action: dict[str, Any]) -> bool:
        text = " ".join(str(action.get(k) or "") for k in ("label", "var_name", "description")).lower()
        return any(word in text for word in ("help", "mouse", "reset", "clicked", "hold", "menu"))

    def clothing(action: dict[str, Any]) -> bool:
        text = " ".join(str(action.get(k) or "") for k in ("label", "var_name", "description")).lower()
        return any(word in text for word in (
            "swap 0", "swapf", "cloth", "dress", "nudity", "neiku",
            "xiongbu", "xiaban", "xiezi", "active_wet", "notail",
        ))

    by_mod: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        by_mod.setdefault(str(action.get("mod_name") or ""), []).append(action)

    for mod_name, items in by_mod.items():
        candidates = [a for a in items if not bad(a) and a.get("targets")]
        if not candidates:
            continue
        preferred = [a for a in candidates if clothing(a)]
        action = (preferred or candidates)[0]
        wire_id = action.get("wire_id")
        if wire_id is None:
            continue
        if mc_core.read_user_var(user_ini_path, controller_ns, f"mc_state_{wire_id}") is not None:
            continue
        values = action.get("values") or []
        if not values:
            continue
        index = 0
        for i, value in enumerate(values):
            if i > 0 and str(value).strip() and str(value).strip() not in ("默认",):
                index = i
                break
        targets = action.get("targets") or []
        option_values = action.get("option_values") or []
        for target, option_list in zip(targets, option_values):
            if index < len(option_list):
                mc_core.set_user_var_full(user_ini_path, str(target), str(option_list[index]))
        mc_core.set_user_var(user_ini_path, controller_ns, f"mc_state_{wire_id}", str(index))


def cleanup_staging(staging_root: Path, library_root: Path | None = None) -> list[str]:
    """删掉控制器自己在 staging 里的产物（manifest 记录的 + `MC_*` + probe）。

    ``library_root`` 传了就走"不要动 Mod 库"护栏：**清单里指向库的路径一律跳过**
    （用户 2026-10-01 硬规则：「任何情况都不要动用户的 mod 库」）。
    """
    staging_root = Path(staging_root)
    removed: list[str] = []
    managed = staging_root / MANAGED_DIR_NAME
    manifest = managed / "active_targets.json"
    if manifest.is_file():
        try:
            for target in json.loads(manifest.read_text(encoding="utf-8")):
                path = Path(target)
                if not fsutil.is_library_safe(library_root, path):
                    continue
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
                    removed.append(str(path))
        except Exception:
            pass
    for name in ("MC_Controller", "_endfieldmodcontroller_managed", "EndfieldModControllerManaged"):
        path = staging_root / name
        if path.exists() and fsutil.is_library_safe(library_root, path):
            shutil.rmtree(path, ignore_errors=True)
            removed.append(str(path))
    probe = staging_root / "MC_Probe.ini"
    if probe.is_file():
        probe.unlink()
        removed.append(str(probe))
    return removed


def _stage_empty(library_root: Path, staging_root: Path, runtime_dir: Path,
                 user_ini_path: Path | None = None) -> dict[str, Any]:
    """selected_ids 显式为空时走这个分支：清空 staging，不 stage 任何 Mod。

    不再退化成"全部激活"。同时把上次的 manifest 与控制器产物清掉，避免残留。
    """
    cleared = 0
    keep = {"DISABLED"}
    # 同样先过"不要动 Mod 库"这道闸（这个分支会清空 staging 下**所有**目录）
    conflict = fsutil.library_conflict(library_root, staging_root)
    if conflict:
        raise LibraryGuardError(
            f"拒绝清空 staging：{conflict}。这会动到你的 Mod 库，已中止（库内文件一个都没动）。"
        )
    # ⚠️ 与 stage_and_prepare 同一条红线（2026-10-01 加固）：**只清我们自己的产物**
    #    （`MC_` 前缀 / manifest 里记过的路径）。用户手动放进 Mods 的目录留着 ——
    #    `staging_mods_dir` 可能就是他自己那份 XXMI 的 Mods，删了就真没了。
    kept_manual: list[str] = []
    manifest_targets: list[str] = []
    manifest_path = staging_root / MANAGED_DIR_NAME / "active_targets.json"
    if manifest_path.is_file():
        try:
            manifest_targets = [
                str(Path(item).resolve())
                for item in json.loads(manifest_path.read_text(encoding="utf-8"))
            ]
        except Exception:
            manifest_targets = []
    try:
        for child in list(staging_root.iterdir()):
            if child.is_dir() and child.name not in keep:
                if not fsutil.is_library_safe(library_root, child):
                    continue                      # 双保险：绝不删库里的任何东西
                if child.name.startswith("MC_") or str(child.resolve()) in manifest_targets:
                    shutil.rmtree(child, ignore_errors=True)
                    cleared += 1
                else:
                    kept_manual.append(child.name)
            elif child.is_file() and child.name.startswith("MC_"):
                try:
                    child.unlink()
                    cleared += 1
                except OSError:
                    pass
    except OSError:
        pass
    # **空选择也必须生成一份空控制器**：否则"一键启动"会在
    # `Controller files are missing. Run prepare first.` 处直接失败 —— 而
    # "还没装任何 Mod 就点一键启动"是完全正常的用法
    # （2026-10-01 从零端到端实测暴露：清空测试目录后 launch() 直接抛错）。
    controller_dir = staging_root / "MC_Controller"
    controller_dir.mkdir(parents=True, exist_ok=True)
    try:
        mc_core.generate_controller_mod(
            [],
            controller_dir,
            user_ini_path=Path(user_ini_path) if user_ini_path else staging_root.parent / "d3dx_user.ini",
        )
    except OSError:
        pass
    return {
        "active": [],
        "report": "empty-selection: 未选择任何 Mod，已清空 staging",
        "patch_count": 0,
        "action_count": 0,
        "cleared": cleared,
        "controller_dir": str(controller_dir),
        # 用户手动放进 Mods 的目录（不是我们生成的）—— 保留原样，交给调用方提示
        "kept_manual": kept_manual,
    }


def stage_and_prepare(
    library_root: Path,
    staging_root: Path,
    runtime_dir: Path,
    selected_ids: Iterable[str] | None = None,
    user_ini_path: Path | None = None,
    all_when_empty: bool = False,
    hotkey_takeover: bool = False,
    allow_same_character: bool = False,
    prefer_internal_dependencies: bool = True,
    log: Any = None,
) -> dict[str, Any]:
    """Plan, stage, patch and generate controller files for the selected mods.

    ⚠ 关于「空列表」：``resolve_active_set`` 里空列表的语义是**全部激活**，这在本项目里
    已经造成过三次事故（每次都是"用控制器启动就崩、手动启动正常"，因为 Mods 被悄悄
    重建成全部 Mod）。所以这里默认把**显式传入的空列表**视为"什么都不选"——
    只清空 staging 并生成空的控制器，不再退化成"全部"。确实需要全部激活时，
    显式传 ``all_when_empty=True``。

    ⚠ 关于 ``hotkey_takeover``：**默认 False = 不改写 Mod 自带热键**（2026-10-01 用户
    拍板：「那个控制面板还没做好，在此之前先恢复快捷键」）。改写热键本意是把操作权交给
    控制器面板，但面板 2026-10-02 已改成**直接发 Mod 自己的原键**（见 `vkey_inject.h`），
    锁键会反过来让面板失效 —— 所以动作由模块开关 `HOTKEY_LOCK_ENABLED` 统一停用
    （判据与代码都保留，见文件顶部那段注释）。
    """
    library_root = library_root.resolve()
    staging_root = staging_root.resolve()
    runtime_dir = runtime_dir.resolve()

    # ⚠️ **「不要动用户的 Mod 库」前置闸**（用户 2026-10-01 定的硬规则：
    #    「任何情况（除用户手动点击移出库外）都不要动用户的 mod 库（包括换位置）」）。
    #    staging 与库只要有重叠（相同 / staging 在库内 / 库在 staging 内），
    #    下面那段"无条件清空 staging"就是把库删光 —— 一条外部反馈正是这么丢的 Mod
    #    （「重装的时候还把我 mod 都删完了，还好我备份了」）。
    #    所以这里**直接拒绝执行**，一个文件都不动，并说清怎么改配置。
    conflict = fsutil.library_conflict(library_root, staging_root)
    if conflict:
        raise LibraryGuardError(
            f"拒绝 staging：{conflict}。这会动到你的 Mod 库，已中止（库内文件一个都没动）。\n"
            f"请到设置页把「Staging Mods 目录」改成**不在 Mod 库里、也不包含 Mod 库**的位置"
            f"（默认的内置 XXMI 就是安全的：runtime\\builtin\\XXMI\\EFMI\\Mods），"
            f"Mod 库（{library_root}）保持原样。"
        )

    if selected_ids is not None and not all_when_empty:
        if not list(selected_ids):
            return _stage_empty(library_root, staging_root, runtime_dir, user_ini_path)

    # First scan only to obtain metadata/identity.
    provisional = mc_core.scan_library(library_root, staging_root)
    active_plan, activation_report = resolve_active_set(
        provisional,
        selected_ids,
        allow_same_character=allow_same_character,
        prefer_internal_dependencies=prefer_internal_dependencies,
    )

    managed_root = staging_root / MANAGED_DIR_NAME
    previous_manifest = managed_root / "active_targets.json"
    manifest_targets: list[str] = []
    if previous_manifest.is_file():
        try:
            manifest_targets = [
                str(Path(item)) for item in json.loads(previous_manifest.read_text(encoding="utf-8"))
            ]
        except Exception:
            manifest_targets = []
    for old_target in manifest_targets:
        if not fsutil.is_library_safe(library_root, Path(old_target)):
            continue          # 清单里的路径若指向库（历史配置变化），一律不删
        shutil.rmtree(Path(old_target), ignore_errors=True)
    for legacy_name in ("_endfieldmodcontroller_managed", "EndfieldModControllerManaged"):
        legacy = staging_root / legacy_name
        if legacy.exists() and fsutil.is_library_safe(library_root, legacy):
            shutil.rmtree(legacy, ignore_errors=True)
    # 无条件清空所有既存的 MC_* 产物：不能只信 manifest —— manifest 丢失时（例如
    # 内置 XXMI 是后复制进来的）旧产物会留在原地，与本次 staging 形成**同角色成对**，
    # EFMI 同时加载两个同角色 Mod 会直接把游戏搞崩（2026-09-27 实测）。
    try:
        for child in staging_root.iterdir():
            if child.name.startswith("MC_") and child.is_dir():
                if not fsutil.is_library_safe(library_root, child):
                    continue
                shutil.rmtree(child, ignore_errors=True)
    except OSError:
        pass
    # ⚠️ **只清「我们自己的产物」**（2026-10-01 数据安全加固）：
    #    以前这里是"清空 staging 目录里**所有** Mod（含有人手动放进去的）"，理由是
    #    "控制器是 Mods 目录的唯一管理者"。这条在真实环境里会咬人：`staging_mods_dir`
    #    完全可以指向**用户自己那份 XXMI 的 Mods**（一份真实诊断包就是
    #    `F:\XXMI Launcher\EFMI\Mods`），而那里躺着用户手工放进去的皮肤 —— 一次
    #    "库为空的一键启动"就会把它们删光（用户红线：「任何情况（除用户手动点击移出库外）
    #    都不要动用户的 mod 库」）。
    #    判据改成两者之一才算我们的：① 名字以 `MC_` 开头（`stage_and_prepare` 的命名）；
    #    ② 在 `active_targets.json` 里记录过（我们上次复制进去的）。其余一律**保留**，
    #    并在结果里列出来，由收编流程/自检提示用户处置 —— 宁可留着让他自己删，也不静默删他文件。
    keep = {"MC_Controller", "DISABLED"}
    previous_targets = {str(Path(item).resolve()) for item in manifest_targets}
    kept_manual: list[str] = []
    try:
        for child in list(staging_root.iterdir()):
            if not child.is_dir() or child.name in keep:
                continue
            if not fsutil.is_library_safe(library_root, child):
                continue
            if child.name in ("_endfieldmodcontroller_managed", "EndfieldModControllerManaged", "ModeControllerManaged"):
                shutil.rmtree(child, ignore_errors=True)
                continue
            if child.name.startswith("MC_") or str(child.resolve()) in previous_targets:
                shutil.rmtree(child, ignore_errors=True)
                continue
            kept_manual.append(child.name)
    except OSError:
        pass
    # 顺手清掉散落的 ini/tsv（保持目录干净）
    for stray in ("MC_Probe.ini",):
        p = staging_root / stray
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass
    for stale in (staging_root / "MC_Controller",):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
    stale_probe = staging_root / "MC_Probe.ini"
    if stale_probe.exists():
        stale_probe.unlink()
    managed_root.mkdir(parents=True, exist_ok=True)

    active_targets: list[str] = []
    # 复制不过去的 Mod（失败**不打断启动**，只是如实记下来：
    # 用户 2026-10-03「启动弹出失败弹窗，但 xxmi 成功拉起」—— 那是误报）
    stage_failed: list[dict[str, str]] = []
    for mod in active_plan:
        dest = staging_root / f"MC_{mc_core.safe_name(mod.group)}_{mc_core.safe_name(mod.name)}"
        if dest.exists():
            # ⚠️ 不能用 `ignore_errors=True`：删不掉（文件被占用 / 只读）时它会静默放过，
            # 紧接着 copytree 就撞上残留报 `[WinError 183] 当文件已存在时，无法创建该文件`
            # —— 用户 2026-10-03 实测就是这个（`MC_加载页 _ 壁纸_xxx\Startscreens` 已存在）。
            # 删干净最好；实在删不掉就交给下面的 `dirs_exist_ok=True` 合并写入，别再抛异常。
            try:
                shutil.rmtree(dest)
            except OSError as exc:
                _log(log, f"WARN staging 旧产物没删干净（将就地覆盖）: {dest.name} ({exc})")
        # ⚠️ **复制单个 Mod 失败绝不能打断整次启动**（用户 2026-10-03：
        #    「启动弹出失败弹窗，**但 xxmi 成功拉起**」—— 报错是 `[WinError 3] 系统找不到指定的路径`，
        #    指个别 dds/ini 复制不过去；而 XXMI 已经在别处拉起来了，用户却看到"启动失败"）。
        #    这类失败多半是瞬时的（杀软正在扫那个文件、EFMI 恰好读了一下目录），所以：
        #    先**重试两次**，仍失败就**记一条警告继续往下走**，让启动流程照常完成。
        ok = False
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                shutil.copytree(mod.path, dest, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("d3dx.ini", "d3dx_user.ini"))
                ok = True
                break
            except OSError as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))   # 给杀软/占用者一点时间松手
        if not ok:
            stage_failed.append({"name": mod.name, "error": str(last_exc)})
            _log(log, f"WARN staging 复制失败（跳过这个 Mod，不打断启动）: {mod.name} ({last_exc})")
            continue
        try:
            for ini_path in mc_core.iter_ini_files(dest):
                mc_core.sanitize_ini_control_flow(ini_path)
        except OSError:
            pass
        active_targets.append(str(dest))
    fsutil.write_text_atomic(
        managed_root / "active_targets.json",
        json.dumps(active_targets, ensure_ascii=False, indent=2),
        newline=chr(10),
    )
    # 加载探针：只用来确认「我们生成的 ini 有没有被加载、`[Present]` 有没有跑」。
    # 2026-10-02（用户批准「探针可以清掉」）：**不再每帧自增** —— 改成每 5 秒记一次，
    # 「计数在涨」这个判据不变，而每帧的开销归零。`$mc_probe_loaded` 是常量，零开销。
    fsutil.write_text_atomic(
        staging_root / "MC_Probe.ini",
        "; EndfieldModController load probe" + chr(10)
        + "[Constants]" + chr(10)
        + "global persist $mc_probe_loaded = 20261001" + chr(10)
        + "global persist $mc_probe_frames = 0" + chr(10)
        + "global persist $mc_probe_t = 0" + chr(10)
        + "[Present]" + chr(10)
        + "if time > $mc_probe_t" + chr(10)
        + "    $mc_probe_t = time + 5" + chr(10)
        + "    $mc_probe_frames = $mc_probe_frames + 1" + chr(10)
        + "endif" + chr(10),
        newline=chr(10),
    )

    staged_mods: list[mc_core.ModInfo] = []
    for mod, target in zip(active_plan, active_targets):
        target_path = Path(target)
        meta = mc_core.load_sidecar(mod.path)
        staged = mc_core._make_mod_info(target_path, target_path, mod.group, mod.kind, meta, staging_root)
        staged.name = mod.name
        for action in staged.actions:
            action.mod_name = mod.name
        staged_mods.append(staged)

    backup_root = runtime_dir / "backups" / "hotkey_patch"
    patch_records: list[mc_core.PatchRecord] = []
    if hotkey_takeover and mc_core.HOTKEY_LOCK_ENABLED:
        # 只有显式打开接管**且**锁键动作没被停用时才改写 Mod 热键 —— 默认保留原键，
        # 让 readme 里写的快捷键、Mod 自带的控制菜单、以及面板发原键都能用
        # （`HOTKEY_LOCK_ENABLED` 为什么是 False 见文件顶部）。
        for mod in staged_mods:
            if mod.is_dependency:
                continue
            # ⚠️ **自带 UI（游戏内菜单）的 Mod 绝不锁键**（2026-10-03 用户：
            #     「有没有什么判据能判断一个 mod 是不是有 ui，**有 ui 就不锁键**」）。
            # 这类 Mod 自己处理输入（`/` 打开菜单、鼠标左右中键选择、方向键/手柄导航），
            # 锁掉它的键 = 把它的菜单入口废掉。
            if mc_core.looks_like_ui_mod(mod.path, [mod.group or "", mod.name or ""], {}):
                _log(log, f"跳过锁键：{mod.name} 自带游戏内菜单（它自己管输入）")
                continue
            patch_records.extend(mc_core.patch_mod_hotkeys(mod.path, backup_root, mod.id))

    controller_dir = staging_root / "MC_Controller"
    if controller_dir.exists():
        shutil.rmtree(controller_dir, ignore_errors=True)
    controller_dir.mkdir(parents=True, exist_ok=True)
    if user_ini_path is None:
        # The EFMI root is the parent of the staging "Mods" directory.  Deriving
        # it from ``runtime_dir`` only works for the legacy layout
        # (<runtime>/EFMI/Mods); with the built-in runtime the real path is
        # <runtime>/builtin/XXMI/EFMI/d3dx_user.ini, so the old rule silently
        # wrote the action queue into a stale file.  AppConfig.user_ini_path
        # applies exactly this same rule - keep the two in sync.
        user_ini_path = staging_root.parent / "d3dx_user.ini"
    else:
        user_ini_path = Path(user_ini_path)
    manifest = mc_core.generate_controller_mod(
        staged_mods, controller_dir, user_ini_path=user_ini_path, library_root=library_root
    )
    try:
        apply_default_action_states(Path(user_ini_path), manifest)
    except OSError:
        pass
    dependency_report = mc_core.check_dependencies(library_root, provisional)

    # Prepare the ReShade add-on base directory without touching the game dir.
    reshade_dir = runtime_dir / "reshade"
    reshade_dir.mkdir(parents=True, exist_ok=True)
    if (controller_dir / "actions.tsv").is_file():
        shutil.copy2(controller_dir / "actions.tsv", reshade_dir / "actions.tsv")
    (reshade_dir / "user_ini_path.txt").write_text(str(user_ini_path), encoding="utf-8", newline="\n")

    return {
        "activation": activation_report.to_dict(),
        "mods": [m.to_dict() for m in staged_mods],
        "patch_count": len(patch_records),
        "actions_manifest": manifest,
        "dependency_report": dependency_report,
        "staging_root": str(staging_root),
        "managed_root": str(managed_root),
        "controller_dir": str(controller_dir),
        "reshade_dir": str(reshade_dir),
        "user_ini_path": str(user_ini_path),
        # 手动放进 Mods（不是我们生成的）的目录 —— 我们**不删**，交给调用方提示/收编
        "kept_manual": kept_manual,
    }
