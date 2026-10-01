"""从上游仓库拉取**乳摇（SBM / SecondaryMotion）的角色参数文件**，补进本地。

用户需求（原话，2026-10-01）：「**在作者改之前，mod 管理器自行拉取新的参数文件**」。
背景：上游 Release 停在 v2.3.5，其角色数据只有 **19 条**（**没有提弗洛斯 `chr_0034_typhoea`**），
而仓库 `main` 分支已经是 **20 条**。已给上游提了 issue
（Sp1cHless/.../issues/5）建议发新版，但在他发之前，管理器自己把缺的角色数据拿到。

## 设计（与 `character_sync` 同一套规矩，逐条都对应踩过的坑）

* **只补不覆盖**：只把上游有、本地没有的**角色条目**加进来；本地已有的角色**原样保留** ——
  用户可能已经调过幅度/频率，整份覆盖等于把他的调校冲掉。所以是"合并"，不是"替换"。
* **绝不碰 `presets/User.json`**：那是用户自己的预设，只处理
  `data/characters.default.json` 与 `presets/Default.json` 两个**默认**文件。
* **只增不减**：上游条目数比本地少（回退/坏数据）时整条跳过，避免把数据越弄越少。
* **非阻塞 + 失败静默**：只在 `api._warm_up()` 的后台线程里跑，24 小时节流
  （`runtime\\_state\\sbm_data_check.json`），任何失败都只写日志，绝不影响启动与首屏。
* **来源可配**：`config.sbm_data_source` 留空 = 上游仓库默认；也可以填
  `owner/repo` 或 `owner/repo@ref`（例如你自己 fork 的仓库 + 分支），改完不必等我们发版。
* **写盘带备份**：改游戏目录里的文件前先留 `<名字>.mc.bak.<时间戳>`，可随时还原。
"""
from __future__ import annotations

import base64
import json
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from . import github
from .config import AppConfig

# 上游仓库（作者已不常维护；用户已 fork 到 jing-hy/... 可自行维护）
DEFAULT_REPO = "Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics"
DEFAULT_REF = "main"

# 只处理这两个「默认」数据文件；`presets/User.json` 是用户自己的，绝不碰。
# 三元组 =（仓库内路径, 本地相对路径, 给人看的名字）—— 仓库里它们在 `SecondaryMotion/` 下，
# 而本地落点是 `<游戏目录>\SecondaryMotion\...`、`assets\secondary_motion\...`，前缀各不相同，
# 所以两者必须分开写（2026-10-01 实测：一开始只写了 `data/...`，请求直接 404）。
FILES: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("SecondaryMotion/data/characters.default.json", ("data", "characters.default.json"), "角色默认数据"),
    ("SecondaryMotion/presets/Default.json", ("presets", "Default.json"), "默认预设"),
)

CACHE_TTL = 24 * 3600
STATE_NAME = Path("_state") / "sbm_data_check.json"
USER_AGENT = "EndfieldModController (+https://github.com/jing-hy/EndfieldModController)"


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def state_path(config: AppConfig) -> Path:
    """节流/状态文件（数据根下，能持久保存）。"""
    return Path(config.runtime_path) / STATE_NAME


def parse_source(config: AppConfig) -> tuple[str, str]:
    """解析数据来源：``(repo, ref)``。

    `config.sbm_data_source` 留空 → 上游默认（`DEFAULT_REPO@main`）；
    也可以写 `owner/repo`（默认 main）或 `owner/repo@分支` —— 例如把自己 fork 的仓库填进去，
    以后在自己的仓库里改数据、push 即生效，不用等我们发版。
    """
    raw = str(getattr(config, "sbm_data_source", "") or "").strip()
    if not raw:
        return DEFAULT_REPO, DEFAULT_REF
    ref = DEFAULT_REF
    if "@" in raw:
        raw, _, ref = raw.partition("@")
        ref = ref.strip() or DEFAULT_REF
    repo = raw.strip().strip("/")
    if repo.count("/") != 1:
        return DEFAULT_REPO, DEFAULT_REF
    return repo, ref


# ---------------------------------------------------------------- 取文件
def fetch_text(repo: str, ref: str, path: str, *, timeout: int = 25) -> str:
    """取仓库里某个文件的**原文**（`path` 是仓库内相对路径，如 `SecondaryMotion/data/...`）。

    两条路线（与 `alerts.py` 同一套）：
      ① GitHub contents API（base64 解码）—— 有 token 时最稳；
      ② 失败则走网页 raw（`github.com/<repo>/raw/<ref>/<path>`，经 fastnet 可借镜像、不吃 API 额度）。
    失败抛异常，由调用方转成"静默跳过 + 日志"。
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    try:
        payload = github.api_get(url, timeout=timeout, use_cache=False)
        content = payload.get("content") if isinstance(payload, dict) else None
        if content:
            encoding = str(payload.get("encoding") or "base64")
            raw = base64.b64decode(content) if encoding == "base64" else str(content).encode("utf-8")
            return raw.decode("utf-8", errors="replace")
        raise ValueError("contents API 没返回 content")
    except Exception as api_error:  # noqa: BLE001
        from . import fastnet

        raw_url = f"https://github.com/{repo}/raw/{ref}/{path}"
        try:
            _final, body = fastnet.fetch(raw_url)
        except Exception as raw_error:  # noqa: BLE001
            raise RuntimeError(f"{path}: API 与网页都取不到（{api_error}；{raw_error}）") from raw_error
        if not body:
            raise RuntimeError(f"{path}: 网页 raw 返回空内容")
        return body if isinstance(body, str) else body.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 合并
def merge_characters(local: dict[str, Any], upstream: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把上游**有、本地没有**的角色条目补进本地（返回新表 + 新增的角色 key）。

    * 本地已有的角色**一律保留原样**（用户可能调过幅度/频率，覆盖等于毁掉他的调校）；
    * 上游条目数比本地少 → 判定为回退/坏数据，原样返回、不补（`[]`）。
    """
    local_chars = local.get("characters") if isinstance(local.get("characters"), dict) else {}
    upstream_chars = upstream.get("characters") if isinstance(upstream.get("characters"), dict) else {}
    if not upstream_chars:
        return local, []
    if len(upstream_chars) < len(local_chars):
        # 上游比本地还少 = 数据回退（或拉到坏文件），宁可不更新
        return local, []

    added = [key for key in upstream_chars if key not in local_chars]
    if not added:
        return local, []

    merged = dict(local)
    merged_chars = dict(local_chars)
    for key in added:
        merged_chars[key] = upstream_chars[key]
    merged["characters"] = merged_chars
    # 表级元信息：本地没有的才补（不覆盖本地已有标注）
    for key in ("schema_version", "_comment", "source", "fetched_at"):
        if key not in merged and key in upstream:
            merged[key] = upstream[key]
    return merged, added


def _write_json(path: Path, payload: dict[str, Any], *, stamp: str) -> Path | None:
    """原子写；**第一次**改这个文件时留一份 `<名字>.mc.bak.<时间戳>` 备份。失败**抛 OSError**。

    ⚠️ 返回值是"备份文件的路径（没备份时 None）"，**不是成功标志** —— 调用方要按异常判断成败
    （曾经用 `is None` 当失败判据，结果"首次写入、无备份可留"的正常情况被误判成写不进去）。
    只在还没有任何 `.mc.bak.*` 时才备份：我们是"只补新增角色"，不会覆盖已有内容，
    留最早那一份原始状态就够回溯了。
    """
    from . import fsutil

    backup: Path | None = None
    if path.is_file():
        existing = list(path.parent.glob(path.name + ".mc.bak.*"))
        if not existing:
            backup = path.with_name(path.name + f".mc.bak.{stamp}")
            shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    fsutil.write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", newline="\n")
    return backup


def _targets(config: AppConfig, relative: tuple[str, ...]) -> list[Path]:
    """要补的文件位置：游戏目录（插件实际读的）→ 随包 assets → 乳摇工具目录。

    游戏目录排第一，因为它是**实际生效**的那份；assets 是"下次铺给新用户"的来源；
    工具目录是管理器自己读的那份（它读不到就显示"没有数据"）。
    """
    from . import secondary_motion

    out: list[Path] = []
    game = secondary_motion.game_dir(config)
    if game is not None:
        out.append(Path(game) / "SecondaryMotion" / Path(*relative))
    out.append(secondary_motion._assets_root(config) / "secondary_motion" / Path(*relative))
    tool = secondary_motion._tool_dir(config)
    if tool is not None:
        out.append(Path(tool) / Path(*relative))
    return out


# ---------------------------------------------------------------- 入口
def sync(
    config: AppConfig,
    *,
    force: bool = False,
    write: bool = True,
    log: Callable[[str], None] | None = None,
    timeout: int = 25,
) -> dict[str, Any]:
    """检查上游角色数据并补进本地（默认 24 小时内不重复请求、失败静默）。

    返回 ``{"ok", "skipped", "changed", "added", "added_names", "repo", "ref", "message"}``：
    调用方（后台预热 / CLI 脚本）据此决定要不要写日志，**任何失败都不该影响启动**。
    """
    now = time.time()
    cache = _read_json(state_path(config))
    if not force and cache.get("at") and (now - float(cache["at"] or 0)) < CACHE_TTL:
        return {"ok": True, "skipped": True, "changed": False, "added": [], "added_names": [],
                "repo": cache.get("repo", ""), "ref": cache.get("ref", ""),
                "message": f"{int(CACHE_TTL / 3600)} 小时内已检查过"}

    repo, ref = parse_source(config)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    added: dict[str, list[str]] = {}
    errors: list[str] = []

    for repo_path, local_parts, label in FILES:
        try:
            text = fetch_text(repo, ref, repo_path, timeout=timeout)
            upstream = json.loads(text)
            if not isinstance(upstream, dict):
                raise ValueError("不是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
            continue

        for target in _targets(config, local_parts):
            local = _read_json(target)
            if not local:
                # 本地没有这份文件（例如游戏目录还没铺过）→ 直接落一份上游的
                merged, new_keys = upstream, list((upstream.get("characters") or {}).keys())
            else:
                merged, new_keys = merge_characters(local, upstream)
            if not new_keys or not write:
                continue
            try:
                _write_json(target, merged, stamp=stamp)
            except OSError as exc:
                errors.append(f"{label}: 写不进 {target}（{exc}）")
                continue
            added.setdefault(label, []).extend(
                k for k in new_keys if k not in added.get(label, [])
            )
            _log(log, f"乳摇数据补充：{target.name} 新增 {len(new_keys)} 个角色（{target.parent}）")

    changed = bool(added)
    total_new = sorted({k for keys in added.values() for k in keys})
    _write_json(state_path(config), {
        "at": int(now), "ok": not errors, "repo": repo, "ref": ref,
        "changed": changed, "added": total_new, "errors": errors[:5],
    }, stamp=stamp)

    for message in errors:
        _log(log, f"乳摇数据检查失败（不影响使用）: {message}")

    return {
        "ok": not errors, "skipped": False, "changed": changed,
        "added": total_new, "added_names": total_new,
        "repo": repo, "ref": ref, "errors": errors,
        "message": (f"新增 {len(total_new)} 个角色" if changed else "已是最新"),
    }


def status(config: AppConfig) -> dict[str, Any]:
    """给界面/日志用的一行状态：本地有几个角色、上次检查什么时候、来源是谁。"""
    from . import secondary_motion

    cache = _read_json(state_path(config))
    targets = _targets(config, ("data", "characters.default.json"))
    counts: dict[str, int] = {}
    for target in targets:
        data = _read_json(target)
        chars = data.get("characters")
        if isinstance(chars, dict):
            counts[str(target)] = len(chars)
    repo, ref = parse_source(config)
    local_max = max(counts.values()) if counts else 0
    return {
        "repo": repo, "ref": ref,
        "local_characters": local_max,
        "files": counts,
        "last_check": int(cache.get("at") or 0),
        "last_added": list(cache.get("added") or []),
        "last_errors": list(cache.get("errors") or []),
        "has_typhoeus": any("chr_0034_typhoea" in (_read_json(t).get("characters") or {}) for t in targets),
    }
