# SPDX-License-Identifier: GPL-3.0-or-later
"""Mod 修复（实验性）/ 回滚 / 移出库。

修复规则（2026-10-19 用户要求，取代旧的"社区修复工具 -1"）：
    把该 Mod 目录下所有 `.ini` 里的 `ps-tN`（**N < 21**）整体 +1 ——
    `ps-t0 → ps-t1`、`ps-t01 → ps-t02`、`ps-t20 → ps-t21`；
    `ps-t21` 及以上、`ps-t70 = ref …` 这类一律不动（用户原话：
    "把mod.ini里面的代码中ps-t小于21的，ps-t后面全部+1，例如ps-t01改成ps-t02"）。

**这不是正规做法**：它只是照着"游戏更新后资源槽位编号变了"的一种社区经验做法猜的，
**不一定有用、也可能把 Mod 改坏**。所以：
  * 界面在动手前必须先把这件事讲清楚，并要求用户先确认
    「已经用最新 RabbitFX 且依然损坏」（RabbitFX 才是作者维护的正规修法）；
  * 每个 Mod 动手前都**整份备份**（`runtime\\backups\\modfix\\`），随时可回滚。

幂等：修复记录写进该 Mod 目录的 `mod.meta.json`（`ps_t_fix` 字段），**不往 ini 里塞标记行**。
旧工具（B站 UP"可可HXL"的修复工具包）会在文件里写
`; PS-T DRAW-SECTION SHIFT -1 APPLIED` —— 那条**仍然会被识别**，只用于提示
"这个 Mod 曾被旧工具 -1 过，再 +1 可能只是回到原样"。

三条硬约定（与旧实现一致）：
* **先备份再动**：备份失败就中止，库里一个字节都不改（备份语义三条件见 CONTRIBUTING）。
* **删除 ≠ 真删**：只移到 `runtime\\backups\\mod-trash\\<时间戳>\\`。
* **只改这个 Mod 自己的 .ini**：不碰 `_deps`、不碰别的 Mod、不碰游戏目录。
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

# ---------------------------------------------------------------- 规则
#: 只替换 N < 21 的槽位（用户要求）；21 及以上是"新的槽位编号"，不该再动。
PS_T_LIMIT = 21
PS_T_RE = re.compile(r"ps-t(\d+)", re.IGNORECASE)
RULE_ID = "ps-t-shift+1:lt21"
RULE_VERSION = 1

#: 旧工具写在 ini 里的标记（**只用作提示**，不再写、也不再作为"已修"判据）。
LEGACY_FIX_MARK = "PS-T DRAW-SECTION SHIFT -1 APPLIED"

SIDECAR_NAME = "mod.meta.json"
META_KEY = "ps_t_fix"
BACKUP_KEEP_PER_MOD = 3
DEFAULT_TIMEOUT = 180          # 保留常量：外部（旧脚本/测试）可能引用

Log = Callable[[str], None] | None


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- sidecar
def sidecar_path(mod_dir: Path) -> Path:
    return Path(mod_dir) / SIDECAR_NAME


def _read_sidecar(mod_dir: Path) -> dict[str, Any]:
    path = sidecar_path(mod_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_sidecar(mod_dir: Path, payload: dict[str, Any]) -> bool:
    from . import fsutil

    try:
        fsutil.write_json(sidecar_path(mod_dir), payload)
    except OSError:
        return False
    return True


def is_fixed(mod_dir: Path) -> dict[str, Any]:
    """这个 Mod 是否已经用 `ps-t+1` 修过（读 sidecar 的修复记录，不扫文件内容）。

    ⚠️ **不拿"文件里还有没有 ps-tN"当判据** —— 没修过的正常 Mod 也有 ps-tN；
    只有我们自己写下的记录才算数。旧工具的 `-1` 标记不在这个高频判据里扫
    （那是 rglob 全目录，get_state 每次都调会拖慢界面），只在 `fix_mod` 时提示。
    """
    data = _read_sidecar(mod_dir)
    record = data.get(META_KEY)
    if not isinstance(record, dict):
        return {"fixed": False, "record": None, "files": []}
    files = [str(item) for item in (record.get("files") or [])]
    return {"fixed": True, "record": record, "files": files}


def has_legacy_shift_minus_one(mod_dir: Path) -> list[str]:
    """旧工具（-1）动过的文件（给弹窗提示用；只在手动修复时才扫）。"""
    hits: list[str] = []
    for ini in Path(mod_dir).rglob("*.ini"):
        try:
            text = ini.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        if LEGACY_FIX_MARK in text:
            hits.append(str(ini.relative_to(mod_dir)))
    return hits


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
    # 回滚完把"已修复"记录清掉（备份里本来就没有这条；这里显式兜底，
    # 免得界面继续显示"已修过/不能再修"）。
    meta = _read_sidecar(dst)
    if META_KEY in meta:
        meta.pop(META_KEY, None)
        _write_sidecar(dst, meta)
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


# ---------------------------------------------------------------- 修复（纯文本改写）
def _decode_ini(raw: bytes) -> tuple[str, str]:
    """把 ini 解成文本并**记住它原来的编码**（写回时要用同一种，免得整文件乱码）。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _encode_ini(text: str, encoding: str) -> bytes:
    try:
        return text.encode(encoding)
    except UnicodeEncodeError:
        return text.encode("utf-8")


def _shift_ps_t(text: str) -> tuple[str, int]:
    """把所有 `ps-tN`（N < 21）改成 `ps-t(N+1)`，返回 (新文本, 替换处数)。"""

    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        digits = match.group(1)
        value = int(digits)
        if value >= PS_T_LIMIT:
            return match.group(0)
        new = str(value + 1)
        if len(new) < len(digits):          # 保留原来的前导零宽度：01 → 02
            new = new.rjust(len(digits), "0")
        count += 1
        head = match.group(0)[: match.start(1) - match.start(0)]
        return head + new

    # ⚠️ 必须自己数"真正改了"的处数：`subn` 返回的是**匹配次数**，
    #    而 ps-t21 / ps-t70 会被匹配但原样返回 ⇒ 用 subn 的计数会把它们也算成"已修"。
    new_text = PS_T_RE.sub(repl, text)
    return new_text, count


def _ini_files(mod_dir: Path) -> list[Path]:
    """这个 Mod 自己的 ini（跳过隐藏路径与 d3dx.ini / d3dx_user.ini —— 与扫描一致）。"""
    from .core import iter_ini_files

    return list(iter_ini_files(Path(mod_dir)))


def fix_mod(config: AppConfig, mod_id: str, mod_dir: Path, *, force: bool = False,
            log: Log = None) -> dict[str, Any]:
    """把一个 Mod 的 `ps-tN`（N < 21）整体 +1。

    步骤：判"已修过"→ 先整份备份 → 逐文件改写（保留编码与换行）→ 写 sidecar 记录。
    任何一步失败都**保持库原样**并把可读原因返回。
    """
    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return {"ok": False, "message": f"Mod 目录不存在: {mod_dir}"}

    state = is_fixed(mod_dir)
    if state["fixed"] and not force:
        record = state["record"] or {}
        return {
            "ok": False, "already": True, "record": record,
            "message": (f"这个 Mod 已经用 ps-t+1 修过一次"
                        f"（{record.get('at', '?')}，替换 {record.get('replacements', '?')} 处）。"
                        "再点一次会变成 +2，可能更坏。"),
        }

    # 先算一遍要改什么：一处都没有就别白备份、也别写记录。
    plan: list[tuple[Path, str, str, int]] = []
    total = 0
    scanned = 0
    for ini in _ini_files(mod_dir):
        scanned += 1
        try:
            raw = ini.read_bytes()
        except OSError as exc:
            _log(log, f"WARN 读不了 {ini.name}: {exc}")
            continue
        text, encoding = _decode_ini(raw)
        shifted, count = _shift_ps_t(text)
        if count:
            plan.append((ini, shifted, encoding, count))
            total += count

    legacy = has_legacy_shift_minus_one(mod_dir)
    if total == 0:
        return {
            "ok": True, "changed": [], "replacements": 0, "files_scanned": scanned,
            "rule": RULE_ID, "rule_version": RULE_VERSION, "legacy_shift_minus_one": legacy,
            "message": (f"扫了 {scanned} 个 ini，没有找到 ps-tN（N<21）这种写法 —— "
                        "这个 Mod 可能不是靠槽位编号出问题的，别硬修"),
        }

    backup = backup_mod(config, mod_id, mod_dir, log=log)
    if not backup.get("ok"):
        return {"ok": False, "message": f"备份失败，已中止修复：{backup.get('message')}"}

    changed: list[str] = []
    written = 0
    for ini, shifted, encoding, count in plan:
        try:
            tmp = ini.with_name(ini.name + ".mc-fix.tmp")
            tmp.write_bytes(_encode_ini(shifted, encoding))
            tmp.replace(ini)
        except OSError as exc:
            _log(log, f"WARN 写回失败 {ini.name}: {exc}")
            continue
        changed.append(ini.relative_to(mod_dir).as_posix())
        written += count

    meta = _read_sidecar(mod_dir)
    record = {
        "rule": RULE_ID, "version": RULE_VERSION,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "replacements": written, "files": changed,
    }
    meta.setdefault("id", mod_id)
    meta.setdefault("name", mod_dir.name)
    meta[META_KEY] = record
    if not _write_sidecar(mod_dir, meta):
        _log(log, f"WARN {mod_dir.name}: 修复已生效，但修复记录没写进 {SIDECAR_NAME}")
        record["sidecar_failed"] = True

    for name in changed:
        _log(log, f"ps-t+1: {mod_dir.name}/{name}")
    if legacy:
        _log(log, f"{mod_dir.name}: 检测到旧工具的 -1 标记（{', '.join(legacy[:3])}）")

    return {
        "ok": True, "changed": changed, "replacements": written,
        "files_scanned": scanned, "rule": RULE_ID, "rule_version": RULE_VERSION,
        "backup": backup, "legacy_shift_minus_one": legacy,
        "message": f"已把 {written} 处 ps-t 槽位 +1（改了 {len(changed)} 个文件）",
    }
