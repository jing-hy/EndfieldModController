"""Activation planning and staging for the PoC.

The library is treated as read-only.  Selected mods are copied into a staging
``Mods`` directory before any INI patch is applied, so original downloads stay
untouched.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import core as mc_core

MANAGED_DIR_NAME = "EndfieldModControllerManaged"


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_active_set(mods: Iterable[mc_core.ModInfo], selected_ids: Iterable[str] | None = None) -> tuple[list[mc_core.ModInfo], ActivationReport]:
    selected_ids = set(selected_ids or [])
    mods = list(mods)
    available_deps = {m.name.lower(): m for m in mods if m.is_dependency}
    candidates = [m for m in mods if not m.is_dependency and (not selected_ids or m.id in selected_ids)]

    chosen: dict[str, mc_core.ModInfo] = {}
    report = ActivationReport()
    for mod in candidates:
        key = mod.conflict_group or mod.group or mod.id
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
    needed: dict[str, mc_core.ModInfo] = {}
    queue = [req.lower() for mod in chosen.values() for req in mod.requires]
    while queue:
        name = queue.pop()
        if name in needed:
            continue
        dep = available_deps.get(name)
        if dep is None:
            continue
        needed[name] = dep
        queue.extend(req.lower() for req in dep.requires)

    report.dependencies = [m.id for m in needed.values()]

    for mod in list(chosen.values()) + list(needed.values()):
        for req in mod.requires:
            if req.lower() not in needed:
                report.missing_dependencies.append(req)

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

        # 从 staging 移除手动目录，避免与随后的 MC_ staging 形成同角色成对
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


def cleanup_staging(staging_root: Path) -> list[str]:
    """Remove EndfieldModController-managed active mods and controller files."""
    staging_root = Path(staging_root)
    removed: list[str] = []
    managed = staging_root / MANAGED_DIR_NAME
    manifest = managed / "active_targets.json"
    if manifest.is_file():
        try:
            for target in json.loads(manifest.read_text(encoding="utf-8")):
                path = Path(target)
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
                    removed.append(str(path))
        except Exception:
            pass
    for name in ("MC_Controller", "_endfieldmodcontroller_managed", "EndfieldModControllerManaged"):
        path = staging_root / name
        if path.exists():
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
    try:
        for child in list(staging_root.iterdir()):
            if child.is_dir() and child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)
                cleared += 1
            elif child.is_file() and child.name.startswith("MC_"):
                try:
                    child.unlink()
                    cleared += 1
                except OSError:
                    pass
    except OSError:
        pass
    return {
        "active": [],
        "report": "empty-selection: 未选择任何 Mod，已清空 staging",
        "patch_count": 0,
        "action_count": 0,
        "cleared": cleared,
        "controller_dir": str(staging_root / "MC_Controller"),
    }


def stage_and_prepare(
    library_root: Path,
    staging_root: Path,
    runtime_dir: Path,
    selected_ids: Iterable[str] | None = None,
    user_ini_path: Path | None = None,
    all_when_empty: bool = False,
) -> dict[str, Any]:
    """Plan, stage, patch and generate controller files for the selected mods.

    ⚠ 关于「空列表」：``resolve_active_set`` 里空列表的语义是**全部激活**，这在本项目里
    已经造成过三次事故（每次都是"用控制器启动就崩、手动启动正常"，因为 Mods 被悄悄
    重建成全部 Mod）。所以这里默认把**显式传入的空列表**视为"什么都不选"——
    只清空 staging 并生成空的控制器，不再退化成"全部"。确实需要全部激活时，
    显式传 ``all_when_empty=True``。
    """
    library_root = library_root.resolve()
    staging_root = staging_root.resolve()
    runtime_dir = runtime_dir.resolve()

    if selected_ids is not None and not all_when_empty:
        if not list(selected_ids):
            return _stage_empty(library_root, staging_root, runtime_dir, user_ini_path)

    # First scan only to obtain metadata/identity.
    provisional = mc_core.scan_library(library_root, staging_root)
    active_plan, activation_report = resolve_active_set(provisional, selected_ids)

    managed_root = staging_root / MANAGED_DIR_NAME
    previous_manifest = managed_root / "active_targets.json"
    if previous_manifest.is_file():
        try:
            for old_target in json.loads(previous_manifest.read_text(encoding="utf-8")):
                shutil.rmtree(Path(old_target), ignore_errors=True)
        except Exception:
            pass
    for legacy_name in ("_endfieldmodcontroller_managed", "EndfieldModControllerManaged"):
        legacy = staging_root / legacy_name
        if legacy.exists():
            shutil.rmtree(legacy, ignore_errors=True)
    # 无条件清空所有既存的 MC_* 产物：不能只信 manifest —— manifest 丢失时（例如
    # 内置 XXMI 是后复制进来的）旧产物会留在原地，与本次 staging 形成**同角色成对**，
    # EFMI 同时加载两个同角色 Mod 会直接把游戏搞崩（2026-09-27 实测）。
    try:
        for child in staging_root.iterdir():
            if child.name.startswith("MC_") and child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
    except OSError:
        pass
    # 清空 staging 目录里**所有** Mod（含有人手动放进去的）—— 控制器是 Mods 目录的
    # 唯一管理者：这里最终只应该存在"用户在 Mod 库勾选的那些"的 MC_* 产物。
    # 2026-09-27 踩过两次：残留的旧 MC_ 或手动放的 Mod 会与本次 staging 形成
    # **同角色成对**，EFMI 同时加载两个同角色 Mod 直接崩游戏。
    keep = {"MC_Controller", ADDON_DISABLED_DIR if False else "DISABLED"}
    try:
        for child in list(staging_root.iterdir()):
            if not child.is_dir() or child.name in keep:
                continue
            if child.name in ("_endfieldmodcontroller_managed", "EndfieldModControllerManaged", "ModeControllerManaged"):
                shutil.rmtree(child, ignore_errors=True)
                continue
            # 非 MC_ 前缀 = 手动放的；MC_ 前缀 = 上次 staging 的产物 —— 都清掉
            shutil.rmtree(child, ignore_errors=True)
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
    for mod in active_plan:
        dest = staging_root / f"MC_{mc_core.safe_name(mod.group)}_{mc_core.safe_name(mod.name)}"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(mod.path, dest, ignore=shutil.ignore_patterns("d3dx.ini", "d3dx_user.ini"))
        try:
            for ini_path in mc_core.iter_ini_files(dest):
                mc_core.sanitize_ini_control_flow(ini_path)
        except OSError:
            pass
        active_targets.append(str(dest))
    (managed_root / "active_targets.json").write_text(
        json.dumps(active_targets, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline=chr(10),
    )
    (staging_root / "MC_Probe.ini").write_text(
        "; EndfieldModController load probe" + chr(10)
        + "[Constants]" + chr(10)
        + "global persist $mc_probe_loaded = 20261001" + chr(10)
        + "global persist $mc_probe_frames = 0" + chr(10)
        + "[Present]" + chr(10)
        + "$mc_probe_frames = $mc_probe_frames + 1" + chr(10),
        encoding="utf-8",
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
    for mod in staged_mods:
        if mod.is_dependency:
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
    manifest = mc_core.generate_controller_mod(staged_mods, controller_dir, user_ini_path=user_ini_path)
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
    }
