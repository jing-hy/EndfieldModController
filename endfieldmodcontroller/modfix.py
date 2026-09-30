"""Mod 修复 / 回滚 / 删除 —— 用社区修复工具（**实验性**）。

工具来源：**B站 up 主「可可HXL」的《终末地Mod修复工具包》v1.5** ——
`Endfield_PS-T_DrawSection_Fix_v2.1.exe`（58 KB，控制台程序）。它把 `d3dx.ini` 里
`checktextureoverride = ps-tN` 的 **N 右移一位**（2026-09-30 实测：`ps-t3→ps-t1`、
`ps-t20→ps-t10`；`ps-t0` 跳过），以适配游戏版本更新后翻倍的资源槽位编号，并在文件里
写一行 `; PS-T DRAW-SECTION SHIFT -1 APPLIED v2.1` 标记（它自己靠这行做幂等）。

三条硬约定（都是实测之后定下来的）：
* **隔离流程**：永远把该 Mod **复制到临时目录**、把工具也放进去跑，**绝不在 Mod 库或
  `Mods` 里跑** —— 工具会生成 `_ps_t_draw_fix_backup_*` 与 `PS_T_Draw_Section_Fix_log.txt`，
  它自带的教程明确要求"这两个不能留在 Mods 里面"。临时目录用完即删，正好满足。
* **改前双备份**：我们自己先整份备份到 `runtime\\backups\\modfix\\<时间戳>\\<Mod>` 并登记
  索引，然后才有「一键回滚」可言（工具自己的备份也在临时目录里、随临时目录一起没了）。
* **删除 ≠ 真删**：只移到 `runtime\\backups\\mod-trash\\<时间戳>\\`，真要彻底删由用户自己做。

⚠ **实验性**：工具的完整筛选判据没逆出来（它只认 `d3dx.ini`、且要求目录像个"完整 Mod"），
**不能保证"本来就好的 Mod 一定不被碰"** —— 所以界面必须标明实验性，且一律"先备份、可回滚"。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .config import PROJECT_ROOT, AppConfig

TOOL_NAME = "Endfield_PS-T_DrawSection_Fix_v2.1.exe"
MANIFEST_NAME = "manifest.json"
FIX_MARK = "PS-T DRAW-SECTION SHIFT -1 APPLIED"
LOG_NAME = "PS_T_Draw_Section_Fix_log.txt"
BACKUP_PREFIX = "_ps_t_draw_fix_backup"
BACKUP_KEEP_PER_MOD = 3
DEFAULT_TIMEOUT = 180

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- 工具就位
def tool_dir(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "modfix"


def tool_path(config: AppConfig) -> Path:
    return tool_dir(config) / TOOL_NAME


def _tool_candidates(config: AppConfig) -> list[Path]:
    """随包资产可能在三个位置：数据根下的 assets、仓库根 assets、包内 assets。"""
    out: list[Path] = []
    base = getattr(config, "base_dir", None)
    if base:
        out.append(Path(base) / "assets" / "modfix" / TOOL_NAME)
    out.append(PROJECT_ROOT / "assets" / "modfix" / TOOL_NAME)
    try:
        out.append(Path(config.runtime_path).parent / "assets" / "modfix" / TOOL_NAME)
    except Exception:  # noqa: BLE001
        pass
    return out


def _expected_sha256(config: AppConfig) -> str:
    """随包清单里的 sha256（用于校验展开出来的工具没被改过）。"""
    for base in _tool_candidates(config):
        manifest = base.parent / MANIFEST_NAME
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        files = data.get("files") or {}
        entry = files.get(TOOL_NAME)
        if isinstance(entry, dict):
            return str(entry.get("sha256") or "")
    return ""


def ensure_tool(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """确保修复工具就位（`runtime\\modfix\\`），必要时从随包资产复制过来。"""
    target = tool_path(config)
    if target.is_file():
        return {"ok": True, "path": str(target), "changed": False}
    for src in _tool_candidates(config):
        if not src.is_file():
            continue
        expected = _expected_sha256(config)
        if expected:
            from . import fsutil

            actual = fsutil.sha256_file(src)
            if actual and actual.lower() != expected.lower():
                return {"ok": False, "message": f"修复工具校验失败（sha256 不符）：{src}"}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        except OSError as exc:
            return {"ok": False, "message": f"复制修复工具失败: {exc}"}
        _log(log, f"修复工具已就位: {target}")
        return {"ok": True, "path": str(target), "changed": True, "source": str(src)}
    return {"ok": False, "message": (
        f"找不到修复工具 {TOOL_NAME}。它随包放在 assets\\modfix\\，正常启动会自动展开到 "
        f"{tool_dir(config)}；也可以手动把 exe 放到 {tool_dir(config)} 再重试"
        f"（从 Release 下载的话，重新展开一次 assets-bundle.zip 即可）。")}


def tool_status(config: AppConfig) -> dict[str, Any]:
    path = tool_path(config)
    return {
        "ready": path.is_file(),
        "path": str(path),
        "name": TOOL_NAME,
        "version": "v1.5 (Endfield_PS-T_DrawSection_Fix_v2.1)",
        "author": "B站 up 主 可可HXL",
        "experimental": True,
    }


# ---------------------------------------------------------------- 状态判定
def is_fixed(mod_dir: Path) -> dict[str, Any]:
    """这个 Mod 是否已经被修复过（靠工具写下的标记行判断）。"""
    marks: list[str] = []
    for ini in Path(mod_dir).rglob("*.ini"):
        try:
            text = ini.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if FIX_MARK in text:
            marks.append(str(ini.relative_to(mod_dir)))
    return {"fixed": bool(marks), "files": marks}


# ---------------------------------------------------------------- 备份 / 回滚
def backup_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "backups" / "modfix"


def trash_root(config: AppConfig) -> Path:
    return Path(config.runtime_path) / "backups" / "mod-trash"


def index_path(config: AppConfig) -> Path:
    return backup_root(config) / "index.json"


def read_index(config: AppConfig) -> dict[str, Any]:
    try:
        data = json.loads(index_path(config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"entries": []}
    if not isinstance(data, dict):
        return {"entries": []}
    data.setdefault("entries", [])
    return data


def _write_index(config: AppConfig, data: dict[str, Any]) -> None:
    from . import fsutil

    try:
        index_path(config).parent.mkdir(parents=True, exist_ok=True)
        fsutil.write_text_atomic(index_path(config),
                                 json.dumps(data, ensure_ascii=False, indent=2), newline="\n")
    except OSError:
        pass


def _unique_dir(parent: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = parent / f"{prefix}{stamp}"
    index = 1
    while candidate.exists():
        candidate = parent / f"{prefix}{stamp}-{index}"
        index += 1
    return candidate


def list_backups(config: AppConfig, mod_id: str = "") -> list[dict[str, Any]]:
    """某个 Mod 的历史备份（新→旧）；不传 mod_id 就返回全部。"""
    entries = [e for e in read_index(config).get("entries", []) if isinstance(e, dict)]
    if mod_id:
        entries = [e for e in entries if e.get("mod_id") == mod_id]
    return [e for e in entries if Path(str(e.get("path") or "")).is_dir()]


def backup_mod(config: AppConfig, mod_id: str, mod_dir: Path, *, log: Log = None) -> dict[str, Any]:
    """整份备份一个 Mod，并登记索引（回滚就靠它）。"""
    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return {"ok": False, "message": f"Mod 目录不存在: {mod_dir}"}
    root = _unique_dir(backup_root(config), "")
    target = root / mod_dir.name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(mod_dir, target)
    except OSError as exc:
        return {"ok": False, "message": f"备份失败: {exc}"}

    data = read_index(config)
    entries = data.get("entries") or []
    entries.insert(0, {
        "mod_id": mod_id, "mod_name": mod_dir.name, "path": str(target),
        "at": int(time.time()), "at_text": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    # 每个 Mod 只留最近 N 份，超出的直接删掉（不然备份会越滚越大）
    kept: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for entry in entries:
        key = str(entry.get("mod_id") or entry.get("mod_name"))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= BACKUP_KEEP_PER_MOD:
            kept.append(entry)
        else:
            shutil.rmtree(Path(str(entry.get("path") or "")), ignore_errors=True)
    data["entries"] = kept
    _write_index(config, data)
    _log(log, f"已备份 {mod_dir.name} → {target}")
    return {"ok": True, "path": str(target), "at_text": kept[0]["at_text"], "name": mod_dir.name}


def _restore_tree(src: Path, dst: Path) -> list[str]:
    """把 dst 恢复成 src 的样子（覆盖不同的、补上缺的、删掉 src 里没有的）。"""
    changed: list[str] = []
    src, dst = Path(src), Path(dst)
    if not dst.exists():
        shutil.copytree(src, dst)
        return ["<整个目录>"]
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        same = False
        if target.is_file():
            try:
                same = target.read_bytes() == item.read_bytes()
            except OSError:
                same = False
        if not same:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            changed.append(str(rel))
    for item in sorted(dst.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = item.relative_to(dst)
        if (src / rel).exists():
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            changed.append(f"删除 {rel}")
        except OSError:
            continue
    return changed


def rollback_mod(config: AppConfig, mod_id: str, *, log: Log = None) -> dict[str, Any]:
    """用**最近一次修复前的备份**还原这个 Mod（一键回滚）。"""
    entries = list_backups(config, mod_id)
    if not entries:
        return {"ok": False, "message": "这个 Mod 没有修复备份（没修过，或备份已被清理）"}
    entry = entries[0]
    src = Path(str(entry["path"]))
    dst = Path(config.library_path) / str(entry.get("mod_name") or src.name)
    if not dst.is_dir():
        return {"ok": False, "message": f"找不到 Mod 目录（可能已被删除或改名）: {dst}"}
    try:
        changed = _restore_tree(src, dst)
    except OSError as exc:
        return {"ok": False, "message": f"回滚失败: {exc}"}
    # 回滚成功后把这条备份消费掉，避免反复回滚同一个状态。
    # ⚠ 按 `path` 匹配而不是对象身份：`read_index()` 每次都会重新读 JSON，
    #   返回的是**新的 dict 对象**，`e is not entry` 永远为真（2026-09-30 单测抓到的）。
    data = read_index(config)
    used = str(entry.get("path") or "")
    data["entries"] = [e for e in (data.get("entries") or [])
                       if str(e.get("path") or "") != used]
    _write_index(config, data)
    _log(log, f"已回滚 {dst.name}（还原 {len(changed)} 项，备份时间 {entry.get('at_text')}）")
    return {"ok": True, "changed": changed, "restored_from": entry.get("at_text", ""),
            "backup_used": str(src), "path": str(dst)}


# ---------------------------------------------------------------- 删除（移到回收区）
def delete_mod(config: AppConfig, mod_dir: Path, *, log: Log = None) -> dict[str, Any]:
    """把 Mod 从库里**移走**（移到 `runtime\\backups\\mod-trash\\<时间戳>\\`，可找回）。"""
    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return {"ok": False, "message": f"Mod 目录不存在: {mod_dir}"}
    target = _unique_dir(trash_root(config), "") / mod_dir.name
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(mod_dir), str(target))
    except (OSError, shutil.Error) as exc:
        return {"ok": False, "message": f"移动失败: {exc}"}
    _log(log, f"已移出 Mod 库: {mod_dir.name} → {target}")
    return {"ok": True, "moved_to": str(target), "name": mod_dir.name,
            "message": "已移出 Mod 库（放在 runtime\\backups\\mod-trash 下，可手动找回）"}


# ---------------------------------------------------------------- 修复（隔离流程）
def _copy_back(src: Path, dst: Path) -> list[str]:
    """把工具改好的文件拷回库（只覆盖内容真的变了的，别乱动时间戳）。"""
    changed: list[str] = []
    for item in Path(src).rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        target = Path(dst) / rel
        same = False
        if target.is_file():
            try:
                same = target.stat().st_size == item.stat().st_size and target.read_bytes() == item.read_bytes()
            except OSError:
                same = False
        if same:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        changed.append(str(rel))
    return changed


def fix_mod(config: AppConfig, mod_id: str, mod_dir: Path, *, log: Log = None,
            timeout: int = DEFAULT_TIMEOUT, skip_if_fixed: bool = False) -> dict[str, Any]:
    """在**临时目录**里对这个 Mod 跑一次修复工具，然后把结果拷回库。

    步骤：确保工具就位 → 自己先整份备份（回滚点）→ 复制到临时目录 → 放工具 → 跑
    → 读工具日志 → 把改动的文件拷回 → 返回摘要。失败一律保留备份、库里不改。
    """
    tool = ensure_tool(config, log=log)
    if not tool.get("ok"):
        return {"ok": False, "message": tool.get("message") or "修复工具不可用"}

    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return {"ok": False, "message": f"Mod 目录不存在: {mod_dir}"}

    state = is_fixed(mod_dir)
    if state["fixed"] and skip_if_fixed:
        return {"ok": True, "skipped": True, "was_fixed": True,
                "message": f"已经修过（{', '.join(state['files'])}），跳过"}

    backup = backup_mod(config, mod_id, mod_dir, log=log)
    if not backup.get("ok"):
        return {"ok": False, "message": f"备份失败，已中止修复：{backup.get('message')}"}

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    tool_log: list[str] = []
    changed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="mc-modfix-") as tmp:
        work_mod = Path(tmp) / mod_dir.name
        try:
            shutil.copytree(mod_dir, work_mod)
            shutil.copy2(tool["path"], Path(tmp) / TOOL_NAME)
        except OSError as exc:
            return {"ok": False, "message": f"准备临时目录失败: {exc}", "backup": backup}

        log_path = Path(tmp) / LOG_NAME
        try:
            proc = subprocess.Popen(
                [str(Path(tmp) / TOOL_NAME)], cwd=str(tmp),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            return {"ok": False, "message": f"启动修复工具失败: {exc}", "backup": backup}

        # 工具做完事会**等一个回车**才退出 —— 所以靠它自己的日志文件判断"做完了"
        deadline = time.time() + max(30, int(timeout))
        while time.time() < deadline:
            if log_path.is_file() and log_path.stat().st_size > 0:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        time.sleep(0.6)                       # 给它写完文件的时间
        try:
            if proc.poll() is None:
                proc.stdin.write(b"\n")       # type: ignore[union-attr]
                proc.stdin.flush()            # type: ignore[union-attr]
                proc.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

        if log_path.is_file():
            try:
                # 工具的日志是 **UTF-8 with BOM**（实测第一行带 \ufeff），用 utf-8-sig 读
                # 才不会把那颗 BOM 带进界面/日志里。
                tool_log = [line.strip() for line in
                            log_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                            if line.strip()]
            except OSError:
                tool_log = []
        try:
            changed = _copy_back(work_mod, mod_dir)
        except OSError as exc:
            return {"ok": False, "message": f"回写库失败: {exc}", "backup": backup, "tool_log": tool_log}

    after = is_fixed(mod_dir)
    for line in tool_log:
        _log(log, f"修复工具: {line}")
    _log(log, f"{mod_dir.name}: 改动 {len(changed)} 个文件"
              + ("，已带上修复标记" if after["fixed"] else "（没有匹配到需要修的内容）"))
    return {
        "ok": True, "changed": changed, "changed_count": len(changed),
        "tool_log": tool_log, "backup": backup, "marked": after["fixed"],
        "was_fixed": state["fixed"],
    }


def fix_all(config: AppConfig, mods: list[Any], *, log: Log = None,
            progress: Callable[[int, int, str], None] | None = None,
            skip_if_fixed: bool = True) -> dict[str, Any]:
    """一键修复所有：逐个走同一套隔离流程，**任一失败不影响其它**。"""
    total = len(mods)
    results: list[dict[str, Any]] = []
    for index, mod in enumerate(mods, 1):
        name = getattr(mod, "name", str(mod))
        if progress:
            try:
                progress(index, total, name)
            except Exception:  # noqa: BLE001
                pass
        try:
            result = fix_mod(config, getattr(mod, "id", name), Path(getattr(mod, "path")), 
                             log=log, skip_if_fixed=skip_if_fixed)
        except Exception as exc:  # noqa: BLE001 —— 单个失败不该中断整批
            result = {"ok": False, "message": str(exc)}
        results.append({
            "id": getattr(mod, "id", name), "name": name,
            "ok": bool(result.get("ok")), "skipped": bool(result.get("skipped")),
            "changed_count": int(result.get("changed_count") or 0),
            "message": str(result.get("message") or ("已修复" if result.get("ok") else "失败")),
        })
    ok = sum(1 for item in results if item["ok"])
    skipped = sum(1 for item in results if item["skipped"])
    changed = sum(item["changed_count"] for item in results)
    return {
        "ok": ok == total, "total": total, "succeeded": ok, "skipped": skipped,
        "changed_total": changed, "results": results,
        "message": f"共 {total} 个：成功 {ok}（其中 {skipped} 个已修过跳过），累计改动 {changed} 个文件",
    }
