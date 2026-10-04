"""远程「公告 / 异常状态预警」——由仓库根目录的 `alerts.json` 下发。

用户 2026-09-30 要求（原话）：「我想做一个功能，加一个动态，从github拉取，每次开管理器的时候
检查，如果有新动态就先弹窗展示，主要用于万一出现大规模封号的时候进行预警与保护」
＋「**动态公告也要保留，用于重大信息发布，但不锁启动**」
＋「在按一键启动的时候如果是**异常状态**要每次都弹弹窗展示情况（情况能通过 github 仓库修改），
**强制用户停留一定秒数（可在仓库配置，默认 10s）**，给出**还原配置（主选项）**、保持配置但不启动、
仍然启动」。

**两档行为**（同一份数据、两种待遇，别再混）：

* `info` / `warning` = **公告**：启动后（首屏就绪）弹一次，看过就不再弹（按 id 记已读）；
  **不锁启动** —— 不强制停留、不影响任何流程，看完关掉照常使用。
* `critical` = **异常状态预警**：**点一次「一键启动」就弹一次**（不记已读、不设开关），
  前端强制停留 `hold_seconds` 秒（仓库可配，默认 10），并且必须三选一：
  **还原配置**（右侧橙色主选项、默认聚焦）/ 保持配置但不启动 / 仍然启动。

数据源：仓库根 `alerts.json`，走 **api.github.com 的 contents 接口**（`raw.githubusercontent.com`
在国内常超时，api 更稳），base64 解码。**每次真查**（不吃 github 那层 30 分钟缓存），
失败**静默**并回退到上次成功缓存 —— 预警要新鲜，但绝不能影响启动、更不能拖住首屏。
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

REPO = "jing-hy/EndfieldModController"
FILE_NAME = "alerts.json"
CACHE_NAME = Path("_state") / "alerts_cache.json"
SEEN_NAME = Path("_state") / "alerts_seen.json"
RESTORE_POINT_NAME = Path("_state") / "alert_restore_point.json"
DEFAULT_HOLD_SECONDS = 10
MAX_HOLD_SECONDS = 120
LEVELS = ("info", "warning", "critical")


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def contents_url() -> str:
    return f"https://api.github.com/repos/{REPO}/contents/{FILE_NAME}"


def _state_path(config: Any, name: Path) -> Path:
    return Path(config.runtime_path) / name


def cache_path(config: Any) -> Path:
    """上次成功拉到的文档（网络失败时回退用它）。"""
    return _state_path(config, CACHE_NAME)


def seen_path(config: Any) -> Path:
    """已读的公告 id（**只管 info/warning**；critical 每次都要弹）。"""
    return _state_path(config, SEEN_NAME)


def restore_point_path(config: Any) -> Path:
    """执行「还原配置」前的开关快照（供撤销）。"""
    return _state_path(config, RESTORE_POINT_NAME)


# ---------------------------------------------------------------- 读写
# ⚠️ 实现已收敛到 `fsutil.read_json` / `fsutil.write_json`（2026-10-04）：
# 同一份"读 JSON 对象、坏了就返回 {}"与"原子写 JSON"原先在 alerts / character_sync /
# sbm_data_sync 各抄了一遍（逐字节相同）。留这两个薄壳是因为测试与诊断脚本直接调它们。
def _read_json(path: Path) -> dict[str, Any]:
    from . import fsutil

    return fsutil.read_json(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    from . import fsutil

    try:
        fsutil.write_json(path, payload)
    except OSError:
        pass


# ---------------------------------------------------------------- 解析
def _clamp_hold(value: Any) -> int | None:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, min(MAX_HOLD_SECONDS, seconds))


def decode_contents(payload: Any) -> dict[str, Any]:
    """把 contents 接口的响应解成文档。

    两种来源都支持：① 线上（`content` 是 base64）；② 测试/本地直接喂文档（顶层有 `alerts`）。
    """
    if not isinstance(payload, dict):
        raise ValueError("alerts.json 的响应不是对象")
    raw = payload.get("content")
    if isinstance(raw, str) and raw.strip():
        try:
            text = base64.b64decode(raw, validate=False).decode("utf-8", errors="replace")
            document = json.loads(text)
        except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"alerts.json 内容无法解析：{exc}") from exc
    elif isinstance(payload.get("alerts"), list):
        document = payload
    else:
        raise ValueError("alerts.json 里既没有 content 也没有 alerts 列表")
    if not isinstance(document, dict):
        raise ValueError("alerts.json 顶层必须是一个对象")
    return document


def normalize(document: dict[str, Any]) -> list[dict[str, Any]]:
    """把文档里的条目规范化；**缺 id 的条目直接丢掉**（没 id 就没法记已读）。"""
    items: list[dict[str, Any]] = []
    for raw in (document.get("alerts") or []):
        if not isinstance(raw, dict):
            continue
        ident = str(raw.get("id") or "").strip()
        if not ident:
            continue
        level = str(raw.get("level") or "info").strip().lower()
        if level not in LEVELS:
            level = "info"
        items.append({
            "id": ident,
            "level": level,
            "title": str(raw.get("title") or "").strip() or "公告",
            "body": str(raw.get("body") or "").strip(),
            "url": str(raw.get("url") or "").strip(),
            "until": str(raw.get("until") or "").strip(),
            "hold_seconds": _clamp_hold(raw.get("hold_seconds")),
            # 版本区间（2026-10-02 加）：留空 = 所有版本都收，两个都给 = 只对那个版本
            "min_version": str(raw.get("min_version") or "").strip(),
            "max_version": str(raw.get("max_version") or "").strip(),
        })
    return items


def is_expired(until: str, now: datetime | None = None) -> bool:
    """`until` 支持 `YYYY-MM-DD` 或 ISO 时间；空 = 永不过期；解析不了 = 当作不过期。"""
    value = str(until or "").strip()
    if not value:
        return False
    moment = now or datetime.now()
    text = value.replace("Z", "+00:00")
    try:
        if len(text) == 10:                     # YYYY-MM-DD：当天结束前有效
            return moment.date() > datetime.strptime(text, "%Y-%m-%d").date()
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return moment > parsed
    except ValueError:
        return False


def hold_seconds(document: dict[str, Any], alert: dict[str, Any] | None = None) -> int:
    """强制停留秒数：条目级 > 文档默认 > 模块默认 10。"""
    value = alert.get("hold_seconds") if isinstance(alert, dict) else None
    if value is None:
        value = _clamp_hold(document.get("default_hold_seconds"))
    if value is None:
        value = DEFAULT_HOLD_SECONDS
    return value


def _version_tuple(value: Any) -> tuple[int, ...]:
    """`"0.9.4"` → `(0, 9, 4)`；取不出数字时给 `(0,)`（与 `dlss5_fetcher` 同一套口径）。"""
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(p) for p in parts) or (0,)


def version_applies(item: dict[str, Any], version: str | None = None) -> bool:
    """这条公告 / 预警适不适用于**本地这个版本**（用户 2026-10-02 要求：「公告要附带版本号，

    是这个版本发公告还是所有版本都能收到，避免后面公告越来越多，管理器也要比对版本号」）。

    规则（**留空 = 不受版本限制**）：
      * `min_version` 与 `max_version` **都不给** ⇒ **所有版本都收**（重大信息 / 安全预警走这条）；
      * 只给 `min_version` ⇒ 从那一版起（含）的所有版本；
      * 只给 `max_version` ⇒ 到那一版为止（含）；
      * **两个都给同一个版本号** ⇒ **只有装了那个版本的人**看得到（"这个版本发的公告"最常用）。

    ⚠️ 读不出本地版本时**不拦**（宁可多提示一次，也别漏掉安全预警）。
    """
    local_text = str(version if version is not None else "").strip()
    if not local_text:
        try:
            from .version import __version__ as local_text  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            local_text = ""
    local = _version_tuple(local_text)
    if not str(local_text or "").strip() or local == (0,):
        return True
    low_text = str(item.get("min_version") or "").strip()
    high_text = str(item.get("max_version") or "").strip()
    if low_text and local < _version_tuple(low_text):
        return False
    if high_text and local > _version_tuple(high_text):
        return False
    return True


# ---------------------------------------------------------------- 拉取
def fetch_document(*, timeout: int = 20) -> dict[str, Any]:
    """真的去仓库拉一次（**不吃 github 缓存**，预警要新鲜）。两条路线都失败才抛异常。

    ① **GitHub API** 的 contents 接口（有 token 时额度 5000/小时）；
    ② **网页 raw 路由**（`github.com/<repo>/raw/main/alerts.json`）—— 经 :mod:`fastnet`，
    直连不通**自动走镜像线路**，而且**不消耗 API 额度**。

    2026-09-30 加②的原因：用户指出「github额度不影响，会自动路由」—— 项目里查组件的
    release 早就"网页优先"了，但公告这条只打了 API。**预警是保护通道，不该被匿名额度
    （60 次/小时）挡住**，所以这里也必须能回退。
    """
    from . import fastnet, github

    errors: list[str] = []
    try:
        payload = github.api_get(contents_url(), timeout=timeout, use_cache=False)
        return decode_contents(payload)
    except Exception as exc:  # noqa: BLE001 —— API 挂了就走网页
        errors.append(f"API 路线: {exc}")
    raw_url = f"https://github.com/{REPO}/raw/main/{FILE_NAME}"
    try:
        _final, body = fastnet.fetch(raw_url, headers={"Accept": "text/plain"}, timeout=timeout)
        document = json.loads(body.decode("utf-8", errors="replace"))
        if not isinstance(document, dict) or document.get("alerts") is None:
            raise ValueError("raw 路线拿到的不是合法的 alerts 文档")
        return document
    except Exception as exc:  # noqa: BLE001
        errors.append(f"网页路线: {exc}")
    raise RuntimeError("；".join(errors))


def load_document(config: Any, *, timeout: int = 20,
                  log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """拉文档；失败时**静默**回退到上次成功缓存（再没有就返回空）。

    ⚠ **正式版只从仓库读**（2026-09-30 用户要求：「正式的版本**不要包含测试的文件和读本地
    文件这个过程**」）—— 早先为离线调试加过"数据根 `alerts.local.json` 优先"那条路，
    测试完已移除：预警是保护通道，不能留下"放个本地文件就能把它挡掉"的口子。
    """
    document: dict[str, Any] = {}
    try:
        document = fetch_document(timeout=timeout)
    except Exception as exc:  # noqa: BLE001 —— 网络/解析什么错都不该影响启动
        cached = _read_json(cache_path(config))
        if cached.get("alerts") is not None:
            _log(log, f"公告/预警检查失败（先用上次缓存）: {exc}")
            return cached
        # 仓库里还没有 alerts.json 时 GitHub 返回 404，而 github 层的文案是"找不到这个仓库…"
        # ——对我们来说这属于**正常状态**（作者还没发过公告），别让日志看着像出了故障。
        hint = "（仓库里还没有 alerts.json，属正常）" if "找不到这个仓库" in str(exc) else ""
        _log(log, f"公告/预警检查跳过{hint}: {exc}")
        return {}
    _write_json(cache_path(config), document)
    return document


# ---------------------------------------------------------------- 对外
def overview(config: Any, *, document: dict[str, Any] | None = None,
             log: Callable[[str], None] | None = None,
             version: str | None = None) -> dict[str, Any]:
    """给界面用的总览。

    * `announcements`：未读且未过期、**且适用于本地版本**的 info/warning（**只弹一次**）；
    * `critical`：未过期、且适用于本地版本的异常状态预警（**每次都返回**，不看已读）。

    `version`：本地版本号（默认取 `endfieldmodcontroller.version.__version__`）—— 用户 2026-10-02
    要求"公告要附带版本号、管理器要比对版本号"，所以**两条链路（公告与预警）都在这一个地方过滤**，
    留空版本区间的条目照旧对所有版本生效。
    """
    doc = document if document is not None else load_document(config, log=log)
    if not doc:
        return {"ok": False, "announcements": [], "critical": [],
                "hold_seconds": DEFAULT_HOLD_SECONDS}
    seen = {str(i) for i in (_read_json(seen_path(config)).get("ids") or [])}
    now = datetime.now()
    announcements: list[dict[str, Any]] = []
    critical: list[dict[str, Any]] = []
    for item in normalize(doc):
        if is_expired(item["until"], now):
            continue
        if not version_applies(item, version):
            continue                      # 这条是给别的版本发的（或只对旧版本有意义）
        if item["level"] == "critical":
            critical.append({**item, "hold_seconds": hold_seconds(doc, item)})
        elif item["id"] not in seen:
            announcements.append(item)
    return {
        "ok": True,
        "announcements": announcements,
        "critical": critical,
        "hold_seconds": hold_seconds(doc),
    }


def mark_seen(config: Any, ids: list[str] | None) -> None:
    """把公告标记为已读（只对 info/warning 有意义；由前端弹过之后调用）。"""
    cleaned = [str(i).strip() for i in (ids or []) if str(i).strip()]
    if not cleaned:
        return
    payload = _read_json(seen_path(config))
    merged = list(dict.fromkeys([str(i) for i in (payload.get("ids") or [])] + cleaned))
    _write_json(seen_path(config), {"ids": merged[-200:], "at": int(time.time())})


# ---------------------------------------------------------------- 还原配置（保护动作）
INJECTION_FIELDS = (
    "dlss5_injection", "efmi_injection", "secondary_motion_injection", "poser_injection",
)


def safe_mode(config: Any, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """「还原配置」：把环境退回**纯原版可启动**状态，全程可逆。

    做两件事（都对应用户「要更强劲的保护」）：
    1. **关掉所有注入开关**（DLSS5 / 服装 Mod / 乳摇 / 摆姿）并重写 XXMI 注入库 → 游戏进程里
       不再挂任何第三方东西；
    2. 调 `game_clean_backup_and_clean` **把游戏目录里的第三方文件先备份再移走** → 连 proxy
       都不留（只移动、不删除，可一键还原）。

    还原前的开关状态存进 `runtime\\_state\\alert_restore_point.json`，`undo_safe_mode()` 可撤回。
    """
    from . import game_clean, launcher

    previous = {name: bool(getattr(config, name, True)) for name in INJECTION_FIELDS}
    _write_json(restore_point_path(config), {"at": int(time.time()), "switches": previous})

    for name in INJECTION_FIELDS:
        setattr(config, name, False)
    try:
        config.save()
    except OSError as exc:
        _log(log, f"还原配置：写配置失败 {exc}")

    injection: dict[str, Any] = {}
    try:
        injection = launcher.ensure_injections(config) or {}
        _log(log, "还原配置：已按新开关重写 XXMI 注入库（现在不注入任何第三方 DLL）")
    except Exception as exc:  # noqa: BLE001
        _log(log, f"还原配置：重写注入库失败 {exc}")

    clean: dict[str, Any] = {}
    try:
        clean = game_clean.backup_and_clean(config, include_plugin_data=True) or {}
    except Exception as exc:  # noqa: BLE001
        _log(log, f"还原配置：清理游戏目录失败 {exc}")

    return {
        "ok": bool(injection) or bool(clean),
        "switches_before": previous,
        "injection": injection,
        "clean": clean,
        "message": "已还原配置：注入开关全部关闭、游戏目录第三方文件已备份移走",
    }


def undo_safe_mode(config: Any, *, log: Callable[[str], None] | None = None) -> dict[str, Any]:
    """撤销「还原配置」：把开关恢复成还原前的样子（游戏目录用「一键还原」那条路走）。"""
    point = _read_json(restore_point_path(config))
    switches = point.get("switches") or {}
    if not isinstance(switches, dict) or not switches:
        return {"ok": False, "message": "没有找到还原点（可能没执行过还原配置）"}
    for name in INJECTION_FIELDS:
        if name in switches:
            setattr(config, name, bool(switches[name]))
    try:
        config.save()
    except OSError as exc:
        _log(log, f"撤销还原配置：写配置失败 {exc}")
        return {"ok": False, "message": str(exc)}
    try:
        from . import launcher

        launcher.ensure_injections(config)
    except Exception as exc:  # noqa: BLE001
        _log(log, f"撤销还原配置：重写注入库失败 {exc}")
    _log(log, "已撤销还原配置：注入开关恢复原状（游戏目录文件请用「一键还原游戏本体」搬回）")
    return {"ok": True, "restored": {k: bool(v) for k, v in switches.items()},
            "message": "注入开关已恢复；游戏目录文件需用「一键还原游戏本体」搬回"}
