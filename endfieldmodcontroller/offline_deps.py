# SPDX-License-Identifier: GPL-3.0-or-later
"""**离线依赖包**：给连不上 GitHub 的机器一次性把"需要下载的东西"带过去。

用户 2026-10-12 要求：「依赖页本来有一个导入随包 zip 的按钮，现在去掉，换成导入依赖包，
放到最上边自动下载依赖旁边，这个适用于**连不上 github** 的，要包含**所有需要下载的**，
然后导入了**自动配置**」。

## 包长什么样（`deps-bundle.zip`）

```
manifest.json                     ← 清单：每个组件叫什么、哪个文件、什么版本、sha256、怎么装
deps/XXMI-Launcher-Portable-v2.4.6.zip
deps/XXMI-PACKAGE-v1.2.2.zip
deps/EFMI-PACKAGE-v1.4.8.zip
deps/ReShade_Setup_6.8.0_Addon.exe
deps/dlss5-feed-1.19.0.zip …
assets/…                          ← 与 `assets-bundle.zip` 完全同构的那一份（DLSS 运行库分卷、
                                     shaders/textures、随包 addon）
```

导入后：

* `deps/*` ⇒ `runtime\\_offline\\<文件名>`（**原始安装包**，不改名、不预解压）；
* `assets/*` ⇒ 交给 `runtime_assets.import_bundle()` 落盘（复用那套"逐条校验分卷"的逻辑）；
* 写索引 `runtime\\_offline\\deps-index.json`（key → 文件名/版本/sha256/来源）。

随后各组件安装链路**离线源优先**：`runtime_deps` 与 `dlss5_fetcher` 先看 `_offline\\` 里有没有
对应的原始安装包 —— 有就用它（不联网），没有才走原来的下载。于是"导入完再点一次一键启动/
一键更新全部组件"就等于**自动配置**，不需要第二套安装逻辑。

## 为什么不做成"和 assets-bundle 合并成一个包"

`assets-bundle.zip` 是**随 exe 走的发行附件**（CI 每次构建都会产出、自动发布），
而离线包只在"有人需要离线"时才打一次；两者生命周期不同。本模块只**读**离线包，
不会去改发行附件的行为。

## 许可边界（不许进包的东西）

⚠️ **2026-10-18 更正**：这里原写「Poser / Streamline / VC++ 三项一律不进包」，而 2026-10-12
逐一读许可证原文后事实是：`Endfield Poser` = **AGPL-3.0**、`Streamline` = **MIT** ——
**都允许再分发**（条件：附许可全文 + 保留版权 + 给出源码途径，包内 `licenses/` 与说明已做），
所以包里一直带着它们。真正进不了包的只有 **VC++ 运行库**（微软条款：必须跑官方安装器，
导入后仍需联网安装，界面会如实标出）。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig

OFFLINE_DIRNAME = "_offline"
INDEX_NAME = "deps-index.json"
MANIFEST_NAME = "manifest.json"
DEPS_PREFIX = "deps/"
ASSETS_PREFIX = "assets/"
#: 包内清单的格式版本（将来改结构时用它判新旧）
BUNDLE_FORMAT = 1


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(message)


def offline_dir(config: AppConfig) -> Path:
    """离线件落点：`<数据根>\\runtime\\_offline`（与 `_downloads` / `_update` 同级）。"""
    return Path(config.runtime_path) / OFFLINE_DIRNAME


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- 索引
def load_index(config: AppConfig) -> dict[str, Any]:
    """读离线索引；没有/坏了都返回空字典（绝不让它影响启动）。"""
    path = offline_dir(config) / INDEX_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_index(config: AppConfig, deps: dict[str, Any], *, source: str = "") -> None:
    root = offline_dir(config)
    root.mkdir(parents=True, exist_ok=True)
    payload = {"built_at": int(time.time()), "source": source, "deps": deps}
    (root / INDEX_NAME).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def index_entries(config: AppConfig) -> dict[str, dict[str, Any]]:
    entries = load_index(config).get("deps")
    return entries if isinstance(entries, dict) else {}


def find_asset(config: AppConfig, asset_name: str) -> Path | None:
    """按**文件名**在 `_offline\\` 里找原始安装包（找不到返回 None）。

    为什么按文件名而不是按 key：上游的资产名自带版本号（`XXMI-Launcher-Portable-v2.4.6.zip`），
    而调用方手里正好有这个名字（`_latest_release_asset()` 的返回值），拿它当键最省事、
    也不会出现"清单里写着 A、磁盘上是 B"的错配。
    """
    if not asset_name:
        return None
    root = offline_dir(config)
    if not root.is_dir():
        return None
    direct = root / asset_name
    if direct.is_file():
        return direct
    try:
        for item in root.rglob(asset_name):
            if item.is_file():
                return item
    except OSError:
        return None
    return None


def entry_for(config: AppConfig, key: str) -> dict[str, Any] | None:
    """某组件在离线索引里的条目（含 `asset` / `version` / `sha256`）。"""
    entry = index_entries(config).get(key)
    return entry if isinstance(entry, dict) else None


def resolve_offline(config: AppConfig, key: str) -> tuple[str, str, str, str] | None:
    """离线优先解析：返回 `(本地路径, 版本, 资产名, sha256)`；离线包没有 ⇒ None。"""
    entry = entry_for(config, key)
    if not entry:
        return None
    asset_name = str(entry.get("asset") or "")
    path = find_asset(config, asset_name)
    if path is None:
        return None
    return (str(path), str(entry.get("version") or ""), asset_name, str(entry.get("sha256") or ""))


# --------------------------------------------------------------------------- 校验
def is_deps_bundle(archive: str | Path) -> bool:
    """这个 zip 是不是**离线依赖包**（用来把旧的 `assets-bundle.zip` 分派回原链路）。

    判据只看一层：能打开、含 `manifest.json`、它的 `kind` 是 `deps-bundle`。
    不在这里做完整校验（那是 `inspect_deps_bundle` 的活儿）。
    """
    path = Path(archive)
    try:
        if not path.is_file() or not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as archive_zip:
            if MANIFEST_NAME not in archive_zip.namelist():
                return False
            data = json.loads(archive_zip.read(MANIFEST_NAME).decode("utf-8"))
    except (OSError, KeyError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile):
        return False
    return isinstance(data, dict) and str(data.get("kind") or "") == "deps-bundle"


def inspect_deps_bundle(archive: str | Path) -> dict[str, Any]:
    """**导入前**逐条校验（用户 2026-10-05 的硬要求：不能"看着成功、之后到处报错"）。

    判据（缺一条就拒绝，且**一个文件都不落盘**）：

    1. 是能打开的 zip，且含 `manifest.json`（会解析、`kind` 对得上）；
    2. 清单里每个 `deps` 条目的文件**都在包里**，大小对得上；填了 `sha256` 的还要 hash 对得上；
    3. 含 `assets/` 时，那份交给 `runtime_assets.inspect_assets_zip()` 再校验一遍（分卷是否齐全）；
    4. 所有成员路径**不许**出现 `..` / 绝对路径（zip slip）。
    """
    path = Path(archive)
    problems: list[str] = []
    if not path.is_file():
        return {"ok": False, "message": f"找不到文件：{path}", "problems": ["文件不存在"]}
    if not zipfile.is_zipfile(path):
        return {"ok": False, "message": "这不是一个能打开的 zip（或已损坏）", "problems": ["不是 zip"]}
    with zipfile.ZipFile(path) as archive_zip:
        names = archive_zip.namelist()
        for name in names:
            normalized = name.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                problems.append(f"包里有不安全的路径：{name}")
        if MANIFEST_NAME not in names:
            return {"ok": False, "message": "包里没有 manifest.json（不是依赖包）",
                    "problems": ["缺 manifest.json"]}
        try:
            manifest = json.loads(archive_zip.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"ok": False, "message": f"manifest.json 解析失败：{exc}",
                    "problems": ["manifest 解析失败"]}
        if str(manifest.get("kind") or "") != "deps-bundle":
            problems.append("manifest.json 的 kind 不是 deps-bundle")
        deps = manifest.get("deps") if isinstance(manifest.get("deps"), dict) else {}
        if not deps and not any(n.startswith(ASSETS_PREFIX) for n in names):
            problems.append("deps 为空、包里也没有 assets/（空包）")
        info_by_name = {item.filename: item for item in archive_zip.infolist()}
        for key, entry in deps.items():
            if not isinstance(entry, dict):
                problems.append(f"{key}: 清单条目不是对象")
                continue
            asset = str(entry.get("asset") or "")
            member = DEPS_PREFIX + asset
            if not asset or member not in info_by_name:
                problems.append(f"{key}: 包里缺 {member}")
                continue
            want_size = int(entry.get("size") or 0)
            got_size = int(info_by_name[member].file_size or 0)
            if want_size and want_size != got_size:
                problems.append(f"{key}: {asset} 大小不符（清单 {want_size} / 实际 {got_size}）")
                continue
            want_sha = str(entry.get("sha256") or "")
            if want_sha:
                got_sha = hashlib.sha256(archive_zip.read(member)).hexdigest()
                if got_sha != want_sha:
                    problems.append(f"{key}: {asset} 的 sha256 与清单不符（包被改过或压坏了）")
        has_assets = any(name.startswith(ASSETS_PREFIX) for name in names)

    if problems:
        return {"ok": False, "message": "；".join(problems[:6]), "problems": problems,
                "deps": list(deps.keys()), "has_assets": has_assets}
    return {"ok": True, "message": f"包里有 {len(deps)} 个组件"
                                    + ("＋随包资产" if has_assets else ""),
            "problems": [], "deps": list(deps.keys()), "has_assets": has_assets,
            "manifest": manifest}


# --------------------------------------------------------------------------- 导入
def import_deps_bundle(config: AppConfig, archive: str | Path,
                       log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """导入离线依赖包：校验 → `deps/` 落到 `_offline\\`、`assets/` 交给 runtime_assets。

    **只在全部校验通过后才动磁盘**（先 inspect，后解包）；`assets/` 那部分依旧走
    `runtime_assets.import_bundle()`（它自己再校验一次分卷、拒绝目录穿越），
    所以两类内容都只有一套判据。
    """
    from . import runtime_assets

    path = Path(archive)
    report = inspect_deps_bundle(path)
    if not report.get("ok"):
        return {"ok": False, "message": f"这个包不能导入：{report.get('message')}",
                "problems": report.get("problems") or []}

    root = offline_dir(config)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    with zipfile.ZipFile(path) as archive_zip:
        for item in archive_zip.infolist():
            name = item.filename.replace("\\", "/")
            if item.is_dir() or not name.startswith(DEPS_PREFIX):
                continue
            target = root / name[len(DEPS_PREFIX):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive_zip.open(item) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
            written.append(target.name)
    save_index(config, report.get("manifest", {}).get("deps") or {}, source=str(path))
    _log(log, f"离线依赖包：已放入 {len(written)} 个组件到 {root}")

    assets_message = ""
    if report.get("has_assets"):
        try:
            assets = runtime_assets.import_bundle(config, path)
            assets_message = str(assets.get("message") or assets.get("kind") or "")
            _log(log, f"离线依赖包里的随包资产：{assets_message}")
        except Exception as exc:  # noqa: BLE001 —— 资产那份失败不影响组件那部分
            assets_message = f"随包资产导入失败：{exc}"
            _log(log, "!! " + assets_message)

    return {
        "ok": True,
        "message": f"已导入 {len(written)} 个组件" + (f"；{assets_message}" if assets_message else ""),
        "components": written,
        "deps": list((report.get("manifest", {}).get("deps") or {}).keys()),
        "assets": assets_message,
    }


def offline_summary(config: AppConfig) -> str:
    """给人看的一句话：离线包里有什么、放哪儿（依赖页/诊断包用）。"""
    entries = index_entries(config)
    if not entries:
        return "没有导入过离线依赖包"
    ok = sum(1 for entry in entries.values() if find_asset(config, str(entry.get("asset") or "")))
    return f"离线依赖包：{len(entries)} 个组件（{ok} 个文件在位）→ {offline_dir(config)}"
