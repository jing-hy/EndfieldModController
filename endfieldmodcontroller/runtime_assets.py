"""随仓库分发的二进制资产（DLSS 运行库 + 无上游的 DLSS5 组件）——首次启动自动展开。

两类资产都放在 `assets/` 下、**压缩 + 按需分卷**，由本模块在启动自检时自动
解压回 `dlss5_dir`，让用户拿到仓库/便携包就能开箱即用：

* `assets/nvngx/` —— `nvngx_dlss.dll` / `nvngx_dlssnr.dll`。后者压缩后 103 MB，
  超过 GitHub 单文件 100 MiB 上限，所以切成 `.part1` / `.part2`；
  NVIDIA 官方 SDK 也**没有** `nvngx_dlssnr.dll` 的直链，只能随包。
* `assets/dlss5/` —— DLSS5 底座里**查不到公开上游**的三个 addon
  （Endfield Enhancer 第一人称、ReShade 面板汉化、RenoDX-DLSS5 汉化版）。

有公开上游的组件（ReShade 底座、DLSS5-Feeder、iMMERSE shader、XXMI/EFMI）
不在这里，走 `dlss5_fetcher` 的在线自动安装。

设计要点（都对应用户踩过的坑）：

* **流式**：按分卷顺序喂 `LZMADecompressor`，全程不把 165 MB 读进内存；
* **先校验后落盘**：解压到同目录的 `.mc-tmp`，比对大小与 sha256 通过后
  `os.replace` 原子改名——中途断电/磁盘满不会留下半截的 DLL；
* **幂等**：目标文件大小与清单一致就直接跳过，不重复解压（每次重解 5~15 秒
  会让"一键启动"变慢）；
* **有进度**：解压是慢操作，必须给 UI/日志可见的进度，不能黑着。

资产由 `scripts/pack_nvngx_assets.py` 生成，清单见各目录下的 `manifest.json`。
"""
from __future__ import annotations

import hashlib
import json
import lzma
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .config import PROJECT_ROOT, AppConfig

# 资产组：目录名 → 说明（都解压到 dlss5_dir）
ASSET_GROUPS: dict[str, str] = {
    "nvngx": "NVIDIA DLSS 运行库（随包，压缩分卷）",
    "dlss5": "DLSS5 组件包（无公开上游，随包内置）",
}
MANIFEST_NAME = "manifest.json"
CHUNK = 1 << 22
TMP_SUFFIX = ".mc-tmp"

Progress = Callable[[str, int, int], None] | None


@dataclass
class AssetResult:
    name: str
    status: str          # present | extracted | missing_source | error
    message: str = ""
    size: int = 0
    sha256: str = ""
    path: str = ""
    group: str = ""
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in {"present", "extracted"}


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        log(message)


def group_root(config: AppConfig, group: str) -> Path | None:
    """某组资产目录（第一个含 manifest.json 的候选）。"""
    subdir = Path("assets") / group
    candidates: list[Path] = []
    # 允许用配置项覆盖根目录（个别用户会把 assets 挪到别处）
    configured = getattr(config, "nvngx_assets_dir", "") or ""
    if configured and group == "nvngx":
        candidates.append(config.resolve_path(configured))
        candidates.append(config.resolve_path(configured).parent / "dlss5")
    candidates.append(PROJECT_ROOT / subdir)
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / subdir)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / subdir)
    candidates.append(Path(__file__).resolve().parents[1] / subdir)

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            if (candidate / MANIFEST_NAME).is_file():
                return candidate
        except OSError:
            continue
    return None


def load_manifest(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def iter_assets(config: AppConfig) -> Iterator[tuple[str, Path, str, dict[str, Any]]]:
    """依次产出 (组名, 资产目录, 文件名, 清单条目)。"""
    for group in ASSET_GROUPS:
        root = group_root(config, group)
        if root is None:
            continue
        entries = load_manifest(root).get("files") or {}
        for name, entry in entries.items():
            if isinstance(entry, dict):
                yield group, root, str(name), dict(entry)


def manifest_entries(config: AppConfig) -> list[tuple[str, Path, str, dict[str, Any]]]:
    return list(iter_assets(config))


# ---------------------------------------------------------------------------
# 随包组件基线校验（2026-09-30 加）
# ---------------------------------------------------------------------------
# 「DLSS5-Feeder」是在线组件（不随包、由 dlss5_fetcher 安装），所以它的基线写在这里。
# ⚠ 2026-09-30 实测更正：**0.1.0（76,800 B）与 1.18.0-beta.1（332,800 B）在终末地上都能
# 正常出帧**（modtest 实测：1.18 从 13:19 跑到 13:22、frame 7200、35 fps、NGX 310.8），
# 所以"与随包不同"**只是差异提示，不是故障判定** —— 别再写"1.18 不会出帧"这种断言
# （此前 README 与自检文案都这么写，是错的）。真不出帧时要看 dlss5-feed.log 与面板 NR 帧。
def _baseline_hint(name: str) -> str:
    """给"缺失/大小不符"补一句"这意味着什么、该怎么修"。

    2026-09-30 issue #3：用户 `runtime\\dlss5\\nvngx_dlssnr.dll` 被动过，自检只报
    "与基线不一致"，看不出后果与动作 —— 而面板那边其实已经在喊 NR 起不来。
    """
    if name == "nvngx_dlssnr.dll":
        return (
            "；这是 DLSS5 神经渲染(NR)用的**签名运行时**，缺了/被换过就会"
            "「NR feature 未绑定、成功 NR 帧恒为 0、最新 NR NGX 结果 0xBAD00001」。"
            "删掉该文件后点「一键启动」会重新展开；若它反复消失，把 runtime\\dlss5 "
            "加进杀毒软件白名单"
        )
    return ""


# 哈希校验只对小资产做：`nvngx_dlss.dll`(59 MB) / `nvngx_dlssnr.dll`(165 MB) 全量 sha256
# 每次自检要读两百多 MB，会把"一键启动"拖慢好几秒 —— 大文件只比大小；几个 addon
# （合计约 6 MB）才逐个校验内容，"大小对但内容被换过"就能查出来了。
MAX_HASH_BYTES = 16 << 20

FEED_NAME = "dlss5-feed.addon64"
FEED_BASELINE_SIZE = 76_800
FEED_BASELINE_SHA256 = "6ea59b3237ed9f1e2bdc6e258518347ccb7e03dfdc2f96fc08addc8974527dad"
# **已知可用的 feed 版本集合**（按字节数认）。它是在线组件，「一键安装/更新全部组件」
# 本来就会装上游最新版 —— 所以"**不等于随包那一版**"**不算异常**，只有落在集合之外才提醒。
#   76,800  = 0.1.0（随包那一版，"built Aug 29"）
#   332,800 = 1.18.0-beta.1（上游最新版；2026-09-30 与 10-02 两次实测在终末地上都正常出帧）
# 用户 2026-10-02 反馈这条每次自检都报、纯属噪音 → 改成集合法。
FEED_KNOWN_GOOD_SIZES = (76_800, 332_800)


def baseline_mismatches(config: AppConfig, *, check_hash: bool = False) -> list[dict[str, Any]]:
    """随包组件与「实测可用基线」的差异列表（供启动自检告警）。

    判据一律用**文件大小 +（可选）sha256**，**不要**用崩溃日志里模块的 `size`
    ——那是 SizeOfImage（内存映像），2026-09-30 我拿它当文件大小用，误判过一整轮。
    """
    target_root = Path(config.dlss5_path)
    mismatches: list[dict[str, Any]] = []

    for group, _root, name, entry in manifest_entries(config):
        expected = int(entry.get("size") or 0)
        want_sha = str(entry.get("sha256") or "")
        path = target_root / name
        if not path.is_file():
            mismatches.append({
                "name": name, "group": group, "kind": "missing",
                "expected": expected, "actual": 0,
                "message": (f"{name} 不在 runtime\\dlss5（随包基线 {expected:,} 字节）"
                            + _baseline_hint(name)),
            })
            continue
        actual = path.stat().st_size
        if expected and actual != expected:
            mismatches.append({
                "name": name, "group": group, "kind": "size",
                "expected": expected, "actual": actual,
                "message": (f"{name} 是 {actual:,} 字节，随包基线 {expected:,} 字节 —— "
                            f"可能被别的整合包替换或手动升级过" + _baseline_hint(name)),
            })
            continue
        if check_hash and want_sha and 0 < expected <= MAX_HASH_BYTES:
            got = sha256_file(path)
            if got and got.lower() != want_sha.lower():
                mismatches.append({
                    "name": name, "group": group, "kind": "hash",
                    "expected": expected, "actual": actual,
                    "message": f"{name} 大小对但内容与基线不一致（sha256 不符）",
                })

    feed = target_root / FEED_NAME
    if feed.is_file():
        size = feed.stat().st_size
        if size not in FEED_KNOWN_GOOD_SIZES:
            mismatches.append({
                "name": FEED_NAME, "group": "online", "kind": "size",
                "expected": FEED_BASELINE_SIZE, "actual": size,
                "message": (f"{FEED_NAME} 是 {size:,} 字节，**不在已知可用的版本**里"
                            f"（随包 {FEED_BASELINE_SIZE:,} = 0.1.0；上游 1.18.0-beta.1 = 332,800）—— "
                            f"若面板「成功NR帧」长期为 0，点「一键安装/更新全部组件」换回上游版"),
            })
        elif check_hash and size == FEED_BASELINE_SIZE:
            got = sha256_file(feed)
            if got and got.lower() != FEED_BASELINE_SHA256:
                mismatches.append({
                    "name": FEED_NAME, "group": "online", "kind": "hash",
                    "expected": FEED_BASELINE_SIZE, "actual": size,
                    "message": f"{FEED_NAME} 大小对但内容被改过（sha256 与随包基线不一致）",
                })
    return mismatches


def baseline_summary(config: AppConfig, *, check_hash: bool = False) -> dict[str, Any]:
    """给自检 / 界面用的一行式摘要。"""
    mismatches = baseline_mismatches(config, check_hash=check_hash)
    total = len(manifest_entries(config)) + 1      # +1 = dlss5-feed.addon64
    return {
        "ok": not mismatches,
        "total": total,
        "mismatches": mismatches,
        "detail": "；".join(item["message"] for item in mismatches),
    }


# 运行时清单里算 sha256 的上限。比 `MAX_HASH_BYTES` 大得多：`nvngx_dlssnr.dll` 有 165 MB，
# 而它恰恰是最需要留指纹的那个（2026-09-30 一整轮误判就是因为它被换过）。
INVENTORY_HASH_LIMIT = 512 << 20


def repair_mismatched(
    config: AppConfig,
    mismatches: list[dict[str, Any]],
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """把"与基线不一致的**随包**组件"重新展开（原文件先备份一份）。

    用户 2026-10-02 的现场：配套里有文件偏离了随包基线 ⇒ 游戏每次启动后几十秒崩在
    `nvgpucomp64`，而自检**只提示、不修**，他最后只能自己把整个 `runtime\\` 删掉重下才好。
    ⇒ 我们自己发出去的组件坏掉，必须**自动修**（准则：「能自动处理的故障，不要用提示来交付」）。

    **在线组件（`dlss5-feed.addon64`）不在这里修** —— 它本来就允许被更新成上游最新版。
    **备份**：`<文件名>.bak-before-baseline-restore`（只留第一份 —— 那才是用户当时在用的）。
    """
    import shutil

    targets = sorted({str(item.get("name")) for item in mismatches
                      if str(item.get("group") or "") != "online"})
    if not targets:
        return {"ok": True, "repaired": [], "failed": [], "message": "没有需要自动修复的随包组件"}
    entries = {
        name: (group, root, entry) for group, root, name, entry in manifest_entries(config)
    }
    target_root = Path(config.dlss5_path)
    repaired: list[str] = []
    failed: list[str] = []
    for name in targets:
        dest = target_root / name
        found = entries.get(name)
        if found is None:
            failed.append(f"{name}（随包资产里没有这一项，只能手动处理）")
            continue
        group, root, entry = found
        if dest.is_file():
            backup = dest.with_name(dest.name + ".bak-before-baseline-restore")
            try:
                if not backup.exists():
                    shutil.copy2(dest, backup)
            except OSError as exc:
                failed.append(f"{name}（备份失败：{exc}，为安全起见没有覆盖它）")
                continue
        try:
            result = ensure_file(config, name, entry, root, group=group, force=True, log=log)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}（重新展开失败：{exc}）")
            continue
        status = str(getattr(result, "status", "") or "")
        if status in ("present", "extracted"):
            repaired.append(name)
            _log(log, f"随包组件已按基线重新展开: {name}")
        else:
            failed.append(f"{name}（{getattr(result, 'message', '') or status or '未知'}）")
    parts: list[str] = []
    if repaired:
        parts.append("已按随包基线重新展开 " + "、".join(repaired))
    if failed:
        parts.append("以下项需要手动处理：" + "；".join(failed))
    return {
        "ok": not failed,
        "repaired": repaired,
        "failed": failed,
        "message": "；".join(parts) or "无需修复",
    }


def runtime_inventory(config: AppConfig, *, with_hash: bool = True) -> list[dict[str, Any]]:
    """**运行时组件清单**：文件名 / 字节 / sha256 / 与随包基线是否一致。

    给崩溃包与诊断包用（用户 2026-10-01 要求「一次抓全」）。2026-10-02 的现场里正是
    因为它缺失，才回答不了"崩溃那一刻装的是哪一版组件" —— 用户把 runtime 删掉重下之后，
    旧现场连清单都不剩，崩因只能停在"配套损坏"这个类别上。
    """
    root = Path(config.dlss5_path)
    if not root.is_dir():
        return []
    baseline = {item["name"]: item for item in baseline_mismatches(config, check_hash=with_hash)}
    rows: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        size = path.stat().st_size
        row: dict[str, Any] = {"name": path.name, "size": size}
        if with_hash and size <= INVENTORY_HASH_LIMIT:
            try:
                row["sha256"] = sha256_file(path)
            except OSError:
                row["sha256"] = ""
        bad = baseline.get(path.name)
        row["baseline"] = "ok" if bad is None else f"{bad['kind']}(基线 {bad['expected']:,})"
        rows.append(row)
    return rows


def inventory_text(config: AppConfig, *, with_hash: bool = True) -> str:
    """把运行时清单渲染成一段可直接塞进崩溃包 / 诊断包的文本。"""
    rows = runtime_inventory(config, with_hash=with_hash)
    if not rows:
        return "（runtime\\dlss5 目录不存在）"
    lines = [f"runtime\\dlss5 共 {len(rows)} 个文件（OK=与随包基线一致，!!=偏离基线）", ""]
    for row in rows:
        mark = "OK" if row.get("baseline") == "ok" else "!!"
        sha = str(row.get("sha256") or "")[:16]
        lines.append(
            f"{mark}  {row['size']:>13,} B  {sha:<16}  {row['name']}   [{row.get('baseline')}]"
        )
    return "\n".join(lines)


def sha256_file(path: Path, progress: Callable[[int, int], None] | None = None) -> str:
    """复用 fsutil 的那一份实现（这里只保留对外签名与 progress 回调语义）。"""
    from . import fsutil

    return fsutil.sha256_file(path, progress)


def _decompress_parts(parts: list[Path], dest: Path, *, progress: Progress, name: str) -> int:
    """按序拼接分卷并流式解压到 dest，返回写出的字节数。"""
    total = sum(part.stat().st_size for part in parts)
    written = 0
    done = 0
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
    with open(dest, "wb") as out:
        for part in parts:
            with open(part, "rb") as fh:
                while True:
                    chunk = fh.read(CHUNK)
                    if not chunk:
                        break
                    done += len(chunk)
                    data = decompressor.decompress(chunk)
                    if data:
                        out.write(data)
                        written += len(data)
                    if progress:
                        progress(name, done, total)
            if decompressor.eof:
                break
        if not decompressor.eof:
            raise lzma.LZMAError("压缩流不完整（分卷缺失或被截断）")
    return written


def ensure_file(
    config: AppConfig,
    name: str,
    entry: dict[str, Any],
    root: Path,
    *,
    group: str = "",
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
) -> AssetResult:
    """确保 `dlss5_dir\\<name>` 在位（缺失/损坏时从内置资产展开）。"""
    target = config.dlss5_path / name
    expected_size = int(entry.get("size") or 0)
    expected_sha = str(entry.get("sha256") or "")

    if target.is_file() and not force:
        size = target.stat().st_size
        if not expected_size or size == expected_size:
            if verify and expected_sha:
                actual = sha256_file(target)
                if actual == expected_sha:
                    return AssetResult(name, "present", f"{size:,} B（已校验）", size, actual, str(target), group)
                _log(log, f"{name}: 内容校验不符，将从内置资产修复")
            else:
                return AssetResult(name, "present", f"{size:,} B 已就位", size, "", str(target), group)
        else:
            _log(log, f"{name}: 现有文件 {size:,} B 与内置版本 {expected_size:,} B 不符，重新展开")

    part_names = [str(p) for p in (entry.get("parts") or [])]
    if not part_names:
        return AssetResult(name, "missing_source", "清单里没有分卷记录", 0, "", str(target), group)
    parts = [root / part for part in part_names]
    missing = [part.name for part in parts if not part.is_file()]
    if missing:
        return AssetResult(
            name, "missing_source",
            f"内置资产缺分卷 {missing}（重新运行 scripts\\pack_nvngx_assets.py）",
            0, "", str(target), group,
        )

    packed_bytes = sum(part.stat().st_size for part in parts)
    try:
        config.dlss5_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return AssetResult(name, "error", f"无法创建 {config.dlss5_path}: {exc}", 0, "", str(target), group)

    try:
        free = shutil.disk_usage(config.dlss5_path).free
        if expected_size and free < expected_size + (16 << 20):
            return AssetResult(
                name, "error",
                f"磁盘空间不足：需要约 {expected_size // 1048576} MB，可用 {free // 1048576} MB",
                0, "", str(target), group,
            )
    except OSError:
        pass

    tmp = target.with_name(target.name + TMP_SUFFIX)
    started = time.time()
    _log(log, f"展开内置资产 {name}（{packed_bytes / 1048576:.1f} MB 压缩包 → {expected_size / 1048576:.1f} MB）")
    actual_sha = ""
    try:
        written = _decompress_parts(parts, tmp, progress=progress, name=name)
        if expected_size and written != expected_size:
            raise lzma.LZMAError(f"解压大小不符：得到 {written:,} B，清单要求 {expected_size:,} B")
        actual_sha = sha256_file(tmp)
        if expected_sha and actual_sha != expected_sha:
            raise lzma.LZMAError(f"sha256 校验失败（得到 {actual_sha[:16]}…，期望 {expected_sha[:16]}…）")
        os.replace(tmp, target)
    except (OSError, lzma.LZMAError, EOFError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        return AssetResult(name, "error", f"展开失败: {exc}", 0, "", str(target), group)
    elapsed = time.time() - started
    return AssetResult(
        name, "extracted",
        f"已从内置资产展开（{target.stat().st_size:,} B，{elapsed:.1f}s）",
        target.stat().st_size, actual_sha, str(target), group, elapsed,
    )


def ensure_all(
    config: AppConfig,
    *,
    progress: Progress = None,
    log: Callable[[str], None] | None = None,
    force: bool = False,
    verify: bool = False,
    allow_fetch: bool = True,
) -> list[AssetResult]:
    """展开所有随包资产里缺失的文件。已就位的直接跳过。

    本地没有 `assets\\`（典型情况：用户只下了单文件 exe，没下资产包）时，
    会尝试从本仓库 Release 拉一次 `assets-bundle.zip` 再展开。
    """
    # **必须在任何分支之前导入**：之前只把它放在"本地没有 assets"的分支里，结果本地
    # 有 assets 时后面的 `dependencies.run_batch_with_retry` 直接 UnboundLocalError
    # （2026-10-01 实测抓到）。
    import time as _time

    from . import dependencies

    found = manifest_entries(config)
    if not found and allow_fetch:
        # 拉资产包是**网络下载**，失败要重试（用户 2026-10-01 要求「全部下载完之后如果
        # 有失败项，就重试，3 次截止」）。以前一次失败就直接报"找不到随包资产"，
        # 界面上看起来就是"完成，但有 1 项失败"。
        for attempt in range(dependencies.MAX_BATCH_RETRIES + 1):
            if attempt:
                _log(log, f"资产包获取失败，重试第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次 …")
            fetched = fetch_bundle(config, log=log, force=bool(attempt))
            if fetched.get("changed"):
                found = manifest_entries(config)
                break
            if attempt >= dependencies.MAX_BATCH_RETRIES:
                if fetched.get("message"):
                    _log(log, f"未能获取资产包：{fetched['message']}")
            else:
                _time.sleep(1.5)
    if not found:
        return [AssetResult(
            "*", "missing_source",
            "找不到随包资产目录 assets\\nvngx、(assets\\dlss5)"
            "（源码/便携包不完整，或用的是旧版 Release）",
        )]

    def worker(item: tuple[str, Path, str, dict[str, Any]], attempt: int) -> AssetResult:
        group, root, name, entry = item
        if attempt:
            _log(log, f"重试展开资产 {name}（第 {attempt}/{dependencies.MAX_BATCH_RETRIES} 次）…")
        result = ensure_file(
            config, name, entry, root,
            group=group, progress=progress, log=log,
            force=force or bool(attempt), verify=verify,
        )
        # **缺失也要重试**（用户 2026-10-01 明确要求）—— 状态不是"已就位 / 已展开"就
        # 当作失败交给重试逻辑；缺失通常是分卷没解开或上次下载中断，force 重跑一次
        # 往往就补上了。只有重试完仍缺，才在结果里如实报"缺失"。
        status = str(getattr(result, "status", "") or "")
        if status not in ("present", "extracted"):
            raise RuntimeError(getattr(result, "message", "") or f"{name}: {status or '缺失'}")
        return result

    # 单项失败不中断其它项，失败项再重试（与下载同一套策略）
    outcomes, _pending = dependencies.run_batch_with_retry(list(found), worker)
    results: list[AssetResult] = []
    for index, (_group, _root, name, _entry) in enumerate(found):
        kind, payload = outcomes[index]
        if kind == "ok":
            results.append(payload)
        else:
            results.append(AssetResult(name, "error", str(payload)))
    return results


# ---------------------------------------------------------------------------
# 资产包：单文件 exe 用户没有本地 assets 时，从 Release 拉一次
# ---------------------------------------------------------------------------
BUNDLE_PATTERN = "assets-bundle"
BUNDLE_STALE_SECONDS = 24 * 3600


def _extract_bundle(archive: Path, dest_root: Path) -> int:
    """只接受压缩包里 `assets/...` 下的条目（防目录穿越 / 防乱写）。"""
    import zipfile

    written = 0
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
            if "assets" not in parts or ".." in parts:
                continue
            relative = parts[parts.index("assets"):]
            target = dest_root.joinpath(*relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            written += 1
    return written


def fetch_bundle(
    config: AppConfig,
    *,
    log: Callable[[str], None] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """从本仓库 Release 下载 `assets-bundle.zip` 并解到工作区（得到 assets\\）。"""
    if not force and any(
        (PROJECT_ROOT / "assets" / group / MANIFEST_NAME).is_file() for group in ASSET_GROUPS
    ):
        return {"ok": True, "changed": False, "message": "本地已有 assets"}

    import urllib.error
    import urllib.request

    from . import github
    from .version import LATEST_API, REPO, USER_AGENT

    stamp = PROJECT_ROOT / "runtime" / "_update" / "bundle-fetch.json"
    if not force and stamp.is_file():
        try:
            last = json.loads(stamp.read_text(encoding="utf-8"))
            if time.time() - float(last.get("at") or 0) < BUNDLE_STALE_SECONDS:
                previous = str(last.get("message") or "")
                # 成功时记的是 "ok:N"（见 remember），直接拿它当"失败原因"会输出
                # "未能获取资产包：ok:5" 这种莫名其妙的话（2026-10-01 修）。
                if previous.startswith("ok:"):
                    previous = "上次已成功展开过内置资产；本次未找到资产包，已跳过（可点重试强制重新拉取）"
                return {"ok": False, "changed": False,
                        "message": previous or "24 小时内已尝试过，跳过"}
        except (OSError, json.JSONDecodeError):
            pass

    def remember(message: str) -> None:
        try:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(json.dumps({"at": int(time.time()), "message": message},
                                        ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # **网页优先 → 失败才打 API**（2026-10-01 修）：原先这里直接请求 `LATEST_API`，
    # 匿名额度一用尽就是 `HTTP Error 403: rate limit exceeded` —— 一份真实诊断包里那台机器
    # **整套随包资产都因此拿不到**（nvngx×2、6 个 shader 标准头、Textures、三个 addon 全缺），
    # 用户看到的就是「缺失 renodx-endfield-enhancer.addon64、无法修复」，界面还一直提示
    # 「随包组件与基线不一致」。自更新检查 / Poser / 公告早就补了网页+镜像回退（`0muo6sow`），
    # **唯独资产包这条路径漏了** —— 现在统一走 `github.releases_latest()`（网页优先、可借镜像）。
    release: dict[str, Any] | None = None
    last_error: object = ""
    for prefer_api in (False, True):
        try:
            release = github.releases_latest(REPO, prefer_api=prefer_api)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
        if isinstance(release, dict):
            break
    if not isinstance(release, dict):
        message = f"查询 Release 失败：{last_error}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    # 网页路线拿不到 `digest`（asset 的 sha256）—— **能补就补**：它用来防止第三方镜像
    # 中转时把大文件换掉。API 额度还在就顺手取一份；取不到也不拦着下载。
    if str(release.get("source") or "") == "web":
        try:
            api_release = github.api_get(LATEST_API)
            digests = {
                str(item.get("name") or ""): str(item.get("digest") or "")
                for item in (api_release.get("assets") or [])
            }
            for item in release.get("assets") or []:
                item["digest"] = digests.get(str(item.get("name") or ""), "")
                item["size"] = item.get("size") or next(
                    (int(a.get("size") or 0) for a in (api_release.get("assets") or [])
                     if str(a.get("name") or "") == str(item.get("name") or "")), 0)
        except Exception:  # noqa: BLE001
            pass

    candidates = [
        asset for asset in (release.get("assets") or [])
        if BUNDLE_PATTERN in str(asset.get("name", "")).lower()
        and str(asset.get("name", "")).lower().endswith(".zip")
    ]
    if not candidates:
        message = (f"Release {release.get('tag_name') or ''} 里没有 {BUNDLE_PATTERN}.zip"
                   "（发布时需把 assets 目录压成该附件一起上传）")
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    asset = sorted(candidates, key=lambda a: int(a.get("size") or 0), reverse=True)[0]
    url = str(asset.get("browser_download_url") or "")
    size_mb = int(asset.get("size") or 0) / 1048576
    _log(log, f"本地没有 assets\\，从 Release 下载资产包 {asset.get('name')}（{size_mb:.0f} MB）")
    target = PROJECT_ROOT / "runtime" / "_update" / str(asset.get("name") or "assets-bundle.zip")
    # 资产包走 fastnet（慢/抖时临时并发、直连不通时临时换镜像）：
    # digest 由 GitHub API 给出，用来防止第三方镜像中转时被替换。
    from . import fastnet

    report = fastnet.download(
        url, target, log=log, expected_sha256=str(asset.get("digest") or ""),
    )
    if not report.ok:
        message = f"下载资产包失败：{report.message}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}
    try:
        written = _extract_bundle(target, PROJECT_ROOT)
    except Exception as exc:  # noqa: BLE001
        message = f"解包资产包失败：{exc}"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    if not written:
        message = "资产包里没有 assets\\ 内容，已忽略"
        remember(message)
        return {"ok": False, "changed": False, "message": message}

    remember(f"ok:{written}")
    _log(log, f"资产包已解出 {written} 个文件")
    return {"ok": True, "changed": True, "files": written, "message": f"已下载并解出 {written} 个文件"}


def asset_report(config: AppConfig) -> dict[str, dict[str, Any]]:
    """给依赖页用的状态：内置包是否可用、本地是否已展开。"""
    report: dict[str, dict[str, Any]] = {}
    for group, root, name, entry in manifest_entries(config):
        target = config.dlss5_path / name
        parts = list(entry.get("parts") or [])
        parts_ok = all((root / part).is_file() for part in parts)
        expected_size = int(entry.get("size") or 0)
        present = target.is_file() and (not expected_size or target.stat().st_size == expected_size)
        packed_bytes = int(entry.get("packed_bytes") or 0)
        report[f"{group}:{name}"] = {
            "display": f"{ASSET_GROUPS.get(group, group)} · {name}",
            "source": f"仓库内置 assets/{group}",
            "install_dir": str(config.dlss5_path),
            "present": bool(present),
            "required": True,
            "needed": not present,
            "status": "已就位" if present else ("待展开" if parts_ok else "内置资产缺失"),
            "enabled": True,
            "version": f"{expected_size / 1048576:.1f} MB",
            "packed": f"{packed_bytes / 1048576:.2f} MB / {len(parts)} 卷" if packed_bytes else "",
            "asset_dir": str(root),
        }
    return report


def stage_report(config: AppConfig) -> dict[str, Any]:
    """资产整体可用性（供"完整性检查"用）。"""
    present = extracted = 0
    problems: list[str] = []
    for group, root, name, entry in manifest_entries(config):
        target = config.dlss5_path / name
        if target.is_file() and target.stat().st_size == int(entry.get("size") or 0):
            extracted += 1
        else:
            missing = [p for p in (entry.get("parts") or []) if not (root / p).is_file()]
            if missing:
                problems.append(f"{name}: 内置资产缺 {missing}")
        present += 1
    return {"total": present, "extracted": extracted, "problems": problems}
