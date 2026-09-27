"""把终末地本体恢复成「完全干净」，而且**先备份、随时可还原**。

为什么需要：这套方案会在游戏目录留下第三方加载器的痕迹 —— `d3dcompiler_47.dll` /
`vulkan-1.dll` 这类 proxy（会转发系统导出并把 `plugin/*.dll` 注入游戏进程）、
`plugin/` 里的 payload、插件写的日志与数据目录。只要这些还在，任何"游戏本体是否
正常"的对照测试都不成立（崩溃日志也会被它们污染）。

做法（**只移动，不删除**）：

1. **备份**：把所有要被移走的东西整体搬进 `runtime\\game_backup\\<时间戳>\\`，
   保持相对路径，并写 `manifest.json`（相对路径 / 大小 / sha256 / 分类 / proxy 还原信息）；
2. **净化**：移走 proxy → 用同目录的 `<name>.bak`（没有就从 System32 复制）把**真正的
   系统模块**放回去，这样官方启动器校验能过；再移走 plugin payload、插件日志、
   插件数据目录、ReShade 痕迹、DLSS5 专属运行库；
3. **还原**：`restore()` 按 manifest 原样搬回来，一步回到净化前的状态。

判定依据：**原版会不会有这个文件** —— 原版终末地目录里不会有 `plugin/`、
不会有覆盖系统 dll 的 proxy、不会有 `nvngx_dlssnr.dll`（DLSS5 专属）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import reshade_integration
from .config import AppConfig

BACKUP_DIR_NAME = "game_backup"
MANIFEST_NAME = "manifest.json"
# 插件在游戏目录里写的东西（原版不可能有）
PLUGIN_DATA_DIRS = ("SecondaryMotion",)
# ReShade 的痕迹（本方案承诺不写游戏目录，出现就是残留）
RESHADE_MARKERS = ("d3d12.dll", "ReShade.ini", "ReShade.log", "ReShadePreset.ini", "reshade-shaders")
# DLSS5 专属运行库：游戏原版**没有**这个文件
DLSS5_ONLY_LIBS = ("nvngx_dlssnr.dll",)
# 方案里的"新版"nvngx（出现即说明游戏原版被替换过）
NEW_NVNGX_SIZES = {"nvngx_dlss.dll": 58977904}

CATEGORY_LABELS = {
    "loader_proxy": "第三方加载器 DLL（proxy，会注入 plugin/*.dll）",
    "plugin_payload": "plugin/ 下会被注入的插件 DLL",
    "plugin_log": "插件日志 / 探针输出",
    "plugin_data": "插件在游戏目录写的数据目录",
    "reshade": "ReShade 注入痕迹",
    "dlss5_lib": "DLSS5 专属运行库（游戏原版没有）",
    "nvngx_overridden": "被替换过的 NVIDIA 运行库",
}

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        log(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backup_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / BACKUP_DIR_NAME


@dataclass
class Finding:
    category: str
    relative: str            # 相对游戏目录
    absolute: str
    is_dir: bool = False
    size: int = 0
    sha256: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "label": CATEGORY_LABELS.get(self.category, self.category),
            "relative": self.relative,
            "absolute": self.absolute,
            "path": self.absolute,
            "is_dir": self.is_dir,
            "size": self.size,
            "sha256": self.sha256,
            "detail": self.detail,
        }


def audit(config: AppConfig) -> dict[str, Any]:
    """列出游戏目录里所有**原版不会有**的东西。"""
    game_dir = reshade_integration.detect_game_dir(config)
    if game_dir is None:
        return {"ok": False, "message": "没有找到游戏目录", "game_dir": "", "findings": [], "clean": False}

    findings: list[Finding] = []

    # ① 加载器 proxy
    for name in reshade_integration.LOADER_PROXY_MODULES:
        path = game_dir / name
        if path.is_file() and reshade_integration.looks_like_loader_proxy(path):
            backup = path.with_name(name + ".bak")
            findings.append(Finding(
                "loader_proxy", name, str(path), size=path.stat().st_size,
                sha256=_sha256(path),
                detail=f"系统原版备份{'存在' if backup.is_file() else '不存在'}（{backup.name}）",
            ))

    # ② plugin/ 里的 payload 与日志（含已被停用但没删掉的副本）
    plugin_dir = game_dir / reshade_integration.PLUGIN_DIR_NAME
    if plugin_dir.is_dir():
        for item in sorted(plugin_dir.iterdir()):
            if not item.is_file():
                continue
            name = item.name.lower()
            disabled = (item.name.endswith(reshade_integration.PLUGIN_DISABLED_SUFFIX)
                        or "disabled" in name)
            if name.endswith(".dll") or disabled:
                findings.append(Finding(
                    "plugin_payload", f"{plugin_dir.name}/{item.name}", str(item),
                    size=item.stat().st_size, sha256=_sha256(item),
                    detail=("已被停用的插件副本（残留，同样不是原版）" if disabled
                            else "会被加载器代理注入游戏进程"),
                ))
            elif item.suffix.lower() in {".txt", ".log"}:
                findings.append(Finding(
                    "plugin_log", f"{plugin_dir.name}/{item.name}", str(item),
                    size=item.stat().st_size, detail="插件写的日志/探针输出",
                ))

    # ③ 插件数据目录 / ReShade 痕迹 / DLSS5 专属运行库
    for name in PLUGIN_DATA_DIRS:
        path = game_dir / name
        if path.is_dir():
            total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            findings.append(Finding(
                "plugin_data", name, str(path), is_dir=True, size=total,
                detail="插件在游戏目录写的数据（characters/presets/logs/runtime）",
            ))
    for name in RESHADE_MARKERS:
        path = game_dir / name
        if path.is_file():
            findings.append(Finding(
                "reshade", name, str(path), size=path.stat().st_size, sha256=_sha256(path),
                detail="ReShade 痕迹：本方案的承诺是不往游戏目录写这些东西",
            ))
        elif path.is_dir():
            total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            findings.append(Finding(
                "reshade", name, str(path), is_dir=True, size=total, detail="ReShade shader 目录残留",
            ))
    for name in DLSS5_ONLY_LIBS:
        path = game_dir / name
        if path.is_file():
            findings.append(Finding(
                "dlss5_lib", name, str(path), size=path.stat().st_size, sha256=_sha256(path),
                detail="DLSS5 神经渲染专用运行库，游戏原版没有这个文件",
            ))

    # ④ 被替换过的 nvngx（原版大小不同即可疑，另看 .game_original 备份）
    for name, new_size in NEW_NVNGX_SIZES.items():
        path = game_dir / name
        if path.is_file() and path.stat().st_size == new_size:
            original = path.with_name(name + ".game_original")
            findings.append(Finding(
                "nvngx_overridden", name, str(path), size=path.stat().st_size, sha256=_sha256(path),
                detail=(f"是方案里的新版（{new_size:,} B）；游戏原版备份"
                        f"{'在 ' + original.name if original.is_file() else '不存在，需重装或校验文件'}"),
            ))

    return {
        "ok": not findings,
        "clean": not findings,
        "game_dir": str(game_dir),
        "findings": [f.to_dict() for f in findings],
        "counts": {category: sum(1 for f in findings if f.category == category)
                   for category in CATEGORY_LABELS if any(f.category == category for f in findings)},
    }


def _copy_tree(src: Path, dest: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _restore_system_module(game_dir: Path, name: str, log: Log) -> dict[str, Any] | None:
    """proxy 移走后，把真正的系统模块放回游戏目录（官方启动器会校验它）。"""
    backup = game_dir / (name + ".bak")
    target = game_dir / name
    if backup.is_file():
        try:
            shutil.copy2(backup, target)
            _log(log, f"已用 {backup.name} 恢复系统模块 {name}（{target.stat().st_size:,} B）")
            return {"name": name, "source": "bak", "sha256": _sha256(target)}
        except OSError as exc:
            _log(log, f"恢复 {name} 失败: {exc}")
            return None
    source = Path(r"C:\Windows\System32") / name
    if source.is_file():
        try:
            shutil.copy2(source, target)
            _log(log, f"已从 System32 复制系统模块 {name}（{target.stat().st_size:,} B）")
            return {"name": name, "source": "system32", "sha256": _sha256(target)}
        except OSError as exc:
            _log(log, f"复制 {name} 失败: {exc}")
            return None
    _log(log, f"⚠ 找不到 {name} 的系统原版（既没有 .bak 也不在 System32），游戏目录里暂时没有这个模块")
    return None


def backup_and_clean(
    config: AppConfig,
    *,
    log: Log = None,
    dry_run: bool = False,
    include_plugin_data: bool = True,
) -> dict[str, Any]:
    """先整体备份，再把游戏目录净化成原版状态（只移动，不删除）。"""
    report = audit(config)
    if not report.get("game_dir"):
        return {"ok": False, "message": report.get("message", "没有找到游戏目录"), "moved": [], "backup_dir": ""}
    game_dir = Path(report["game_dir"])
    findings = [Finding(**{k: v for k, v in item.items() if k in Finding.__dataclass_fields__})
                for item in report["findings"]]
    if not include_plugin_data:
        findings = [f for f in findings if f.category != "plugin_data"]
    if not findings:
        return {"ok": True, "message": "游戏目录已经是干净的（没有发现非原版文件）",
                "moved": [], "backup_dir": "", "game_dir": str(game_dir)}

    stamp = _stamp()
    root = backup_root(config) / stamp
    # 同一秒内连做两次备份不能互相覆盖（第一次的"净化前"状态才是有价值的那份）
    if root.exists():
        index = 2
        while (backup_root(config) / f"{stamp}-{index}").exists():
            index += 1
        stamp = f"{stamp}-{index}"
        root = backup_root(config) / stamp
    files_dir = root / "files"
    if dry_run:
        return {
            "ok": True, "dry_run": True, "game_dir": str(game_dir), "backup_dir": str(root),
            "moved": [f.to_dict() for f in findings],
            "message": f"预演：将备份并移走 {len(findings)} 项",
        }

    entries: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    restored_modules: list[dict[str, Any]] = []
    errors: list[str] = []

    for finding in findings:
        source = Path(finding.absolute)
        dest = files_dir / finding.relative
        try:
            _copy_tree(source, dest)          # ① 先复制一份到备份区
            if source.is_dir():
                shutil.rmtree(source)          # ② 确认备份成功后才移除原位
            else:
                source.unlink()
        except OSError as exc:
            errors.append(f"{finding.relative}: {exc}")
            _log(log, f"⚠ 处理 {finding.relative} 失败: {exc}")
            continue
        entries.append({**finding.to_dict(), "backup_relative": finding.relative})
        moved.append(finding.to_dict())
        _log(log, f"备份并移走 [{finding.category}] {finding.relative}")

    # proxy 移走后必须把系统模块补回去，否则游戏会缺 d3dcompiler_47/vulkan-1
    for finding in findings:
        if finding.category != "loader_proxy":
            continue
        name = Path(finding.relative).name
        module = _restore_system_module(game_dir, name, log)
        if module:
            restored_modules.append(module)

    manifest = {
        "stamp": stamp,
        "created_at": int(time.time()),
        "game_dir": str(game_dir),
        "entries": entries,
        "restored_modules": restored_modules,
        "errors": errors,
    }
    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    except OSError as exc:
        errors.append(f"写清单失败: {exc}")

    return {
        "ok": not errors,
        "game_dir": str(game_dir),
        "backup_dir": str(root),
        "moved": moved,
        "restored_modules": restored_modules,
        "errors": errors,
        "message": f"已备份并移走 {len(moved)} 项；备份在 {root}",
    }


def list_backups(config: AppConfig) -> list[dict[str, Any]]:
    root = backup_root(config)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(root.iterdir(), reverse=True):
        manifest = item / MANIFEST_NAME
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({
            "stamp": data.get("stamp") or item.name,
            "created_at": data.get("created_at", 0),
            "entries": len(data.get("entries") or []),
            "game_dir": data.get("game_dir", ""),
            "path": str(item),
        })
    return rows


def restore(config: AppConfig, *, stamp: str = "", log: Log = None) -> dict[str, Any]:
    """按备份清单把游戏目录还原成净化前的样子。"""
    backups = list_backups(config)
    if not backups:
        return {"ok": False, "message": "没有找到任何游戏目录备份", "restored": []}
    target = next((b for b in backups if b["stamp"] == stamp), backups[0]) if stamp else backups[0]
    root = Path(target["path"])
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "message": f"备份清单损坏: {exc}", "restored": []}

    game_dir = Path(manifest.get("game_dir") or "")
    if not game_dir.is_dir():
        return {"ok": False, "message": f"原游戏目录不存在: {game_dir}", "restored": []}

    restored: list[str] = []
    errors: list[str] = []
    # 先删掉我们补进去的系统模块，再把 proxy 搬回来（顺序反了会被覆盖）
    for module in manifest.get("restored_modules") or []:
        path = game_dir / str(module.get("name") or "")
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            errors.append(f"清理 {path.name}: {exc}")

    for entry in manifest.get("entries") or []:
        relative = str(entry.get("relative") or "")
        if not relative:
            continue
        source = root / "files" / relative
        dest = game_dir / relative
        if not source.exists():
            errors.append(f"备份里缺少 {relative}")
            continue
        try:
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            _copy_tree(source, dest)
            restored.append(relative)
            _log(log, f"还原 {relative}")
        except OSError as exc:
            errors.append(f"{relative}: {exc}")

    return {
        "ok": not errors,
        "stamp": target["stamp"],
        "game_dir": str(game_dir),
        "restored": restored,
        "errors": errors,
        "message": f"已从 {target['stamp']} 的备份还原 {len(restored)} 项",
    }
