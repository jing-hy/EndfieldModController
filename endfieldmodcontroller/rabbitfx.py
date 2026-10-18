# SPDX-License-Identifier: GPL-3.0-or-later
"""RabbitFX 随包分发、展开与升级（2026-10-03 用户要求：「**那把他随包**」）。

**RabbitFX 是什么**（作者 caverabbit，GameBanana 651557，CC BY-NC-ND 4.0）：
终末地 Mod 的**共享 shader 特效前置** —— 用 `[ShaderRegex*]` 正则改写角色 shader，
往里插额外贴图槽（`t60/t61` Glow、`t70–t74` Diffuse/Lightmap/Normal/Discard/Rain），
并做去马赛克与 HSV 调色。庄方宜的模块化菜单包（`snaccubus-…-modularmenumod`）等
Mod 明确要求它（它的 `README.txt` 第一行就写着 `Requires RabbitFX library`）。

**为什么要随包**：它本体只有 **6 KB**（上游 `28_2d258.zip` = 6,204 B），
而从 GameBanana 拉取在国内线路上可能只有 8 KB/s（实测），为这 6 KB 让用户等/失败不值得。
随包放在 `assets/rabbitfx/`，启动自检时展开。

**装到哪**：`<Mod 库>/_deps/RabbitFX` —— **与 `dependencies.json` 里声明依赖时的安装位置
一致**，这样"随包展开"和"按依赖下载"两条路落到同一个地方，不会各铺一份。

⚠️ **作者的硬性警告**：`Having multiple RabbitFXs will cause unexpected behaviours and
game crashes … only ever have one instance of RabbitFX anywhere in your mods folder`。
所以 `find_duplicates()` 会在库里发现第二份时报出来。

**2026-10-18：内置版本升级**（用户：「把内置的更新一下」+「这个插件要接进依赖更新检查」）。
内置从 v2.6（`v26_b2546.zip`）升到 v2.8（`28_2d258.zip`：新增 `CommandListCleanTextures`
纹理清理通道、shader 正则放宽 CB3/CB4/CB5 的匹配）。升级**不是无脑覆盖**：
`ensure_bundled()` 只升级「确认是我们铺过的那一代」的目录（目录里受管文件的 sha256 必须
逐一对上随包 manifest 里 `history`/当前代的记录），升级前整份备份到
`runtime\\backups\\rabbitfx/<时间戳>/`；用户自己放的那份/改过的 ini **一律不动**。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

Log = Callable[[str], None] | None

# 展开目标（相对 Mod 库）—— 与 dependencies.json 的 install_dir 保持一致
INSTALL_REL = Path("_deps") / "RabbitFX"
# 判定"已装好"的必需文件
REQUIRED_FILE = "RabbitFX.ini"
# 随包目录名
ASSET_GROUP = "rabbitfx"
# 上游 mod id（GameBanana）+ 我们写的来源 marker
GAME_BANANA_ID = 651557
MARKER_NAME = ".endfieldmodcontroller_source.json"
MANIFEST_NAME = "manifest.json"
# 版本号就写在 ini 第一行的注释里：`; RabbitFX -Arknights Endfield- Version 2.8`
_VERSION_RE = re.compile(r"RabbitFX[^\n]*?Version\s+([0-9]+(?:\.[0-9]+)*)", re.IGNORECASE)


def _log(log: Log, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def assets_root(config: AppConfig | None = None) -> Path:
    """随包资产根目录。

    `assets` 位于**数据根**（exe 所在目录），与 `config.json` / `runtime` / `library` 同级。
    这才是"从 Release 下载 exe + assets-bundle.zip"解出来的形态；`__file__` 在打包后指向
    PyInstaller 的临时解压目录，那里没有 assets（见 `secondary_motion._assets_root` 的说明）。
    """
    if config is not None:
        base = getattr(config, "base_dir", None) or getattr(config, "data_root", None)
        if base:
            return Path(base) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def bundled_source(config: AppConfig) -> Path | None:
    """随包里那份 RabbitFX 的目录（不存在返回 None）。"""
    candidate = assets_root(config) / ASSET_GROUP
    if (candidate / REQUIRED_FILE).is_file():
        return candidate
    return None


def install_dir(config: AppConfig) -> Path:
    """展开目标：`<Mod 库>/_deps/RabbitFX`。"""
    return Path(config.library_path) / INSTALL_REL


def is_installed(config: AppConfig) -> bool:
    return (install_dir(config) / REQUIRED_FILE).is_file()


def bundled_manifest(config: AppConfig) -> dict[str, Any]:
    """随包 manifest（版本说明 + 每代文件的 sha256）；读不到返回空字典。"""
    src = bundled_source(config)
    if src is None:
        return {}
    try:
        data = json.loads((src / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def bundled_version(config: AppConfig) -> str:
    """随包里那一代的版本号（`2.8`）；读不到返回空串。"""
    return str(bundled_manifest(config).get("mod_version") or "").strip()


def local_version(config: AppConfig) -> str:
    """本机 `_deps/RabbitFX` 那份的版本号（从 ini 第一行注释读）。

    读不到就返回空串 = "不知道版本"（不猜、不拿文件大小顶替）。
    """
    ini = install_dir(config) / REQUIRED_FILE
    try:
        head = ini.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return ""
    match = _VERSION_RE.search(head)
    return match.group(1) if match else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload(files: dict[str, Any]) -> dict[str, str]:
    """从 manifest 的 `files` 里取**内容文件**（排除 marker 与 manifest 自身）。

    marker（`remote_version`/`updated_at`）会被依赖更新链改写，拿它判"是不是我们铺的"
    会误判成"用户改过"；`manifest.json` 本来就不进 Mod 目录。
    """
    out: dict[str, str] = {}
    for name, entry in (files or {}).items():
        key = str(name).replace("\\", "/")
        if key in (MARKER_NAME, MANIFEST_NAME):
            continue
        sha = str((entry or {}).get("sha256") or "") if isinstance(entry, dict) else ""
        if sha:
            out[key] = sha.lower()
    return out


def _generations(config: AppConfig) -> list[dict[str, Any]]:
    """随包里**所有认识的代**：当前代 + `history` 里每一代（新→旧）。"""
    manifest = bundled_manifest(config)
    if not manifest:
        return []
    gens: list[dict[str, Any]] = []
    current = _payload(manifest.get("files") or {})
    if current:
        gens.append({"version": str(manifest.get("mod_version") or ""), "files": current})
    history = manifest.get("history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            payload = _payload(item.get("files") or {})
            if payload:
                gens.append({"version": str(item.get("mod_version") or ""), "files": payload})
    return gens


def _match_generation(target: Path, gens: list[dict[str, Any]]) -> dict[str, Any] | None:
    """目标目录里**受管文件**逐一对上哪一代（对上几代都行，返回最新匹配的那代）。

    判据必须**够硬**：只比"文件存在"不够（用户可能改过 ini 又留着同名文件），
    所以逐文件比 sha256；目录里多出来的文件（用户启用的 `ShaderCacheSettings.ini` 等）
    不参与判定、升级时也不删。
    """
    for gen in gens:
        files = gen["files"]
        if not files:
            continue
        if not all((target / name).is_file() for name in files):
            continue
        if all(_sha256(target / name).lower() == sha for name, sha in files.items()):
            return gen
    return None


def find_duplicates(config: AppConfig) -> list[Path]:
    """在 Mod 库里找**除了目标之外**的 RabbitFX（作者警告多份会崩）。

    只扫库的第一层与 `_deps` 一层，够用且便宜；命中就交给调用方如实报出来。
    """
    out: list[Path] = []
    target = install_dir(config).resolve() if is_installed(config) else None
    try:
        roots = [Path(config.library_path), Path(config.library_path) / "_deps"]
    except (OSError, AttributeError):
        return out
    for root in roots:
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                if not (child / REQUIRED_FILE).is_file():
                    continue
                try:
                    if target is not None and child.resolve() == target:
                        continue
                except OSError:
                    pass
                out.append(child)
        except OSError:
            continue
    return out


def _unique_backup_dir(config: AppConfig) -> Path:
    """`runtime\\backups\\rabbitfx/<时间戳>/`，同一秒两次也不互相覆盖（备份只增不删）。"""
    root = Path(config.runtime_path) / "backups" / "rabbitfx"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = root / stamp
    index = 2
    while candidate.exists():
        candidate = root / f"{stamp}-{index}"
        index += 1
    return candidate


def _backup_target(config: AppConfig, target: Path, *, from_version: str, to_version: str) -> Path | None:
    """升级前把**整份**目标目录复制到 `runtime\\backups\\rabbitfx/`，并先写清单。

    备份语义（项目红线）：① 清单**先落盘**（`status=in_progress`），搬完改成 `complete`；
    ② 备份名唯一（`_unique_backup_dir`），**绝不覆盖**上一次的备份。
    """
    dest = _unique_backup_dir(config)
    payload: dict[str, Any] = {
        "status": "in_progress",
        "kind": "rabbitfx",
        "from_version": from_version,
        "to_version": to_version,
        "source": str(target),
        "created_at": int(time.time()),
        "files": {},
    }
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "backup.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        copied = dest / "RabbitFX"
        shutil.copytree(target, copied)
        for item in sorted(copied.rglob("*")):
            if item.is_file():
                rel = item.relative_to(copied).as_posix()
                payload["files"][rel] = _sha256(item)
        payload["status"] = "complete"
        (dest / "backup.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return dest
    except OSError as exc:
        _log(None, f"RabbitFX 备份失败（不升级）：{exc}")
        return None


def _apply_bundle(src: Path, target: Path, payload: dict[str, str]) -> None:
    """把随包里的**受管文件**逐份写到目标（写临时文件再原子替换，用户多余文件不动）。"""
    for name in payload:
        source = src / name
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".mc-tmp")
        shutil.copyfile(source, tmp)
        tmp.replace(dest)
    marker_src = src / MARKER_NAME
    if marker_src.is_file():
        shutil.copyfile(marker_src, target / MARKER_NAME)


def ensure_bundled(config: AppConfig, *, log: Log = None) -> dict[str, Any]:
    """把随包的 RabbitFX 铺到 `<Mod 库>/_deps/RabbitFX`（幂等 + **可安全升级**）。

    四种结果：
      * `installed`  —— 原来没有，铺了一份；
      * `updated`    —— 原来那份**确认是我们铺过的旧代**，备份后就地升级到随包这代；
      * `present`    —— 已就位且是最新那代（或**用户自己那份/改过的那份**，一律不动）；
      * `already_elsewhere` —— 库里别处已有一份 RabbitFX（作者警告多份会崩），不铺；
      * `missing`    —— 随包资产不存在，由依赖下载兜底。

    ⚠️ 为什么现在允许"改"用户目录里的东西（2026-10-18）：这个目录是**程序自己铺的产物**，
    不是用户的 Mod。内置升到新版而库里那份还是旧版 ⇒ 用户实际用的永远是旧 shader 规则，
    等于"内置没更新"。所以只对**逐文件 sha256 对得上随包历史代**的目录动手，
    动手前整份备份，用户自己改过/自己放的**完全不动**。
    """
    target = install_dir(config)
    src = bundled_source(config)
    gens = _generations(config)
    newest = gens[0] if gens else None

    if is_installed(config):
        dup = find_duplicates(config)
        if dup:
            _log(log, "RabbitFX 已就位；但库里还有其它副本（作者警告多份会崩）："
                      + "、".join(p.name for p in dup))
        matched = _match_generation(target, gens)
        if newest is None:
            return {"ok": True, "status": "present", "dir": str(target)}
        if matched is not None and matched["files"] == newest["files"]:
            return {"ok": True, "status": "present", "dir": str(target),
                    "version": newest["version"]}
        if matched is None:
            # 不是我们铺的（用户自己下的/自己改过）⇒ 保持原样，但把原因说清楚。
            _log(log, "库里那份 RabbitFX 不是随包产物（或已被改动），保留不动")
            return {"ok": True, "status": "present", "dir": str(target),
                    "kept": True,
                    "version": local_version(config),
                    "bundled_version": (newest or {}).get("version", ""),
                    "message": "库里那份不是随包产物（或已被改动），保留不动"}
        if src is None:
            return {"ok": False, "status": "missing",
                    "message": "随包 assets\\rabbitfx 不存在（重新展开一次 assets-bundle.zip 即可）"}
        # ── 升级：先备份，再逐文件替换 ──────────────────────────────────
        backup = _backup_target(config, target,
                                from_version=str(matched["version"]),
                                to_version=str(newest["version"]))
        if backup is None:
            return {"ok": False, "status": "error",
                    "message": "升级前备份失败（为安全起见没有改动任何文件）"}
        try:
            _apply_bundle(src, target, newest["files"])
        except OSError as exc:
            return {"ok": False, "status": "error",
                    "message": f"升级失败：{exc}（备份在 {backup}）",
                    "backup": str(backup)}
        _log(log, f"RabbitFX：{matched['version']} → {newest['version']}（备份 {backup}）")
        return {"ok": True, "status": "updated", "dir": str(target),
                "from_version": str(matched["version"]),
                "version": str(newest["version"]),
                "backup": str(backup)}

    dup = find_duplicates(config)
    if dup:
        _log(log, "库里已有一份 RabbitFX（" + "、".join(p.name for p in dup)
                  + "），不再重复铺随包那份（作者警告多份会导致异常与崩溃）")
        return {"ok": True, "status": "already_elsewhere", "dir": str(dup[0])}

    if src is None:
        return {"ok": False, "status": "missing",
                "message": "随包 assets\\rabbitfx 不存在（重新展开一次 assets-bundle.zip 即可）"}

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # 先拷到临时目录再改名：中断也不会留下半份
        tmp = target.with_name(target.name + ".mc-tmp")
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp)
        # 随包的 manifest.json 是给我们自己看的，不进 Mod 目录
        (tmp / MANIFEST_NAME).unlink(missing_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        tmp.rename(target)
    except OSError as exc:
        return {"ok": False, "status": "error", "message": f"展开失败：{exc}"}

    _log(log, f"RabbitFX：随包展开到 {target}")
    return {"ok": True, "status": "installed", "dir": str(target),
            "version": (newest or {}).get("version", "")}


def latest_upstream(log: Log = None) -> dict[str, Any]:
    """联网查 GameBanana 上**当前主文件**的版本（给「检查更新」用）。

    复用 `dependencies` 的两段现成逻辑：拉 ProfilePage + 按 Main File 挑文件，
    不另造一条通道（那边刚修过"名字匹配不上就退化成 examples.zip"的坑）。
    查不到就抛异常，由调用方记进 `report["errors"]`，**不静默返回空**。
    """
    from . import dependencies

    profile = dependencies._fetch_json(
        f"https://gamebanana.com/apiv11/Mod/{GAME_BANANA_ID}/ProfilePage")
    info = dependencies._latest_gamebanana_file(profile, "")
    if not info:
        raise RuntimeError("GameBanana 页面上没有可用的主文件")
    version = str(info.get("_sVersion") or "").strip()
    if not version:
        # 少见的兜底：文件没标版本时，用 mod 级 `_sVersion` 的第一个字段（`2.8 | 4.6E4`）
        version = str(profile.get("_sVersion") or "").split("|")[0].strip()
    _log(log, f"RabbitFX 上游最新：{version}（{info.get('_sFile')}）")
    return {
        "version": version,
        "file": str(info.get("_sFile") or ""),
        "url": str(info.get("_sDownloadUrl") or ""),
        "size": int(info.get("_nFilesize") or 0),
        "gamebanana_id": GAME_BANANA_ID,
    }
