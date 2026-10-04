"""从**官网**同步《终末地》角色名表（一手来源，唯一可信）。

为什么要有它（用户 2026-09-30 要求：「**管理器要带最新角色名，可以固化拉最新角色名称
的脚本，每次启动后非阻塞检查**」）：角色名表决定新导入的 Mod 能不能自动归类到角色，
而**同角色互斥**是防崩的第一道闸。官方上新干员后，随包那份 `characters.json` 就旧了，
以前只能手工抓 —— 现在固化成脚本 + 启动后台自检。

**只认官网**（用户准则原话「不是，你直接去官网拉」）：第三方聚合站的译名有硬错误
（秋栗写成 karin、弧光写成 ikut、狼卫写成 wolfguard…），官网 `endfield.hypergryph.com/operator`
全对。页面是 Next.js 服务端渲染，每个角色是：

    <img src=".../typhoea.87cfb4cd.png">
    <div class="OperatorItem_nameText...">提弗洛斯</div>
    <div class="OperatorItem_codename...">// Typhoeus</div>
    <div class="OperatorItem_index...">01<!-- --> / <!-- -->33</div>

设计要点（都对应踩过的坑）：
* **非阻塞**：只在后台预热线程（`api._warm_up`）里跑；失败**静默**，不影响启动；
* **有缓存**：默认 24 小时内不重复请求（`runtime\\_state\\characters_check.json`）；
* **不丢手工数据**：合并时**保留本地 aliases**（社区简称是我们手工补的，官网没有）；
* **写到数据根**：`runtime\\_state\\characters.json` —— exe 是 onefile，包内路径在临时
  目录里、写不进去也不持久；`core.set_characters_override()` 让 core 优先读它。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

SOURCE_URL = "https://endfield.hypergryph.com/operator"
CACHE_TTL = 24 * 3600
STATE_NAME = Path("_state") / "characters_check.json"
LATEST_NAME = Path("_state") / "characters.json"
USER_AGENT = "EndfieldModController/0.1 (+https://github.com/jing-hy/EndfieldModController)"

# 用 CSS module 的**语义前缀**匹配（哈希后缀会随构建变，前缀不会）
_NAME_RE = re.compile(r'OperatorItem_nameText[^"]*"[^>]*>([^<]+)<')
_CODE_RE = re.compile(r'OperatorItem_codename[^"]*">\s*//\s*([^<]+)<')
_INDEX_RE = re.compile(r'OperatorItem_index[^"]*">\s*(\d+)[^0-9]{0,24}?(\d+)')
_IMG_RE = re.compile(r"https://[^\"'\s]*/([a-z0-9_]+)\.[0-9a-f]{6,}\.png", re.I)
# 一个角色块内部 name → codename 的距离上限（防止"某个角色缺代号"时错配到下一个）
_MAX_GAP = 2000


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log:
        try:
            log(message)
        except Exception:  # noqa: BLE001
            pass


def latest_path(config: Any) -> Path:
    """运行时更新版角色表的位置（数据根下，能持久保存）。"""
    return Path(config.runtime_path) / LATEST_NAME


def cache_path(config: Any) -> Path:
    """最近一次检查的记录（用于 24 小时节流）。"""
    return Path(config.runtime_path) / STATE_NAME


# ---------------------------------------------------------------- 解析
def parse_official(html: str) -> dict[str, Any]:
    """把官网干员页解析成 ``{"total": 33, "characters": [...]}``。

    做法：先收集四类锚点（名字 / 代号 / index / 图标 URL）**带位置**，再以每个名字为
    锚点，取它后面最近的代号与 index、前面最近的图标（页面里就是这个顺序）。
    """
    names = [(m.start(), m.group(1).strip()) for m in _NAME_RE.finditer(html)]
    codes = [(m.start(), m.group(1).strip()) for m in _CODE_RE.finditer(html)]
    indexes = [(m.start(), int(m.group(1)), int(m.group(2))) for m in _INDEX_RE.finditer(html)]
    images = [(m.start(), m.group(1).lower()) for m in _IMG_RE.finditer(html)]

    characters: list[dict[str, Any]] = []
    total = 0
    for pos, name in names:
        codename = ""
        for code_pos, code_value in codes:
            if pos < code_pos <= pos + _MAX_GAP:
                codename = code_value
                break
        index, page_total = 0, 0
        for idx_pos, idx_value, idx_total in indexes:
            if pos < idx_pos <= pos + _MAX_GAP:
                index, page_total = idx_value, idx_total
                break
        key = ""
        for img_pos, img_value in reversed(images):
            if img_pos < pos:
                key = img_value
                break
        total = max(total, page_total)
        aliases = [alias for alias in (name, codename, key) if alias]
        characters.append({
            "index": index, "name": name, "codename": codename, "key": key, "aliases": aliases,
        })
    return {"total": total or len(characters), "characters": characters,
            "source": SOURCE_URL, "fetched_at": time.strftime("%Y-%m-%d")}


def fetch_official(*, timeout: int = 25) -> dict[str, Any]:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    parsed = parse_official(html)
    if len(parsed["characters"]) < 10:
        # 页面结构变了就得说清楚，别悄悄把表清空
        raise RuntimeError(f"官网页面结构可能变了：只解析到 {len(parsed['characters'])} 位角色")
    return parsed


# ---------------------------------------------------------------- 合并
def merge_payload(local: dict[str, Any], official: dict[str, Any]) -> dict[str, Any]:
    """把官网结果合并进本地表。

    三条规矩（都对应对过的坑）：
      * **本地 aliases 一律保留** —— 社区简称（「小羊」「塞希」）官网没有，丢了就认不出
        用户的 Mod；
      * **官网同名条目先聚合** —— 官网把男女管理员列成两条（都叫「管理员」，key 分别是
        `endministrator` / `endministrator1`），不聚合会在表里造出重复角色；
      * **官网没列、本地有的要保留**（下架 / 改名），别让已有 Mod 突然识别不出来。
    """
    local_items: dict[str, dict[str, Any]] = {}
    for item in (local.get("characters") or []):
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            local_items[str(item["name"]).strip()] = dict(item)
    by_code = {str(item.get("codename") or "").strip().lower(): name
               for name, item in local_items.items() if item.get("codename")}

    # 官网可能把同一角色列多条 → 先按 canonical 名聚合（保持官网顺序）
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for item in (official.get("characters") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if name not in grouped:
            order.append(name)
        grouped.setdefault(name, []).append(item)

    merged: list[dict[str, Any]] = []
    added: list[str] = []
    updated = 0
    for name in order:
        items = grouped[name]
        codename = next((str(i.get("codename") or "").strip() for i in items
                         if str(i.get("codename") or "").strip()), "")
        key = next((str(i.get("key") or "").strip() for i in items
                    if str(i.get("key") or "").strip()), "")
        official_aliases = [str(a).strip() for i in items
                            for a in (i.get("aliases") or []) if str(a).strip()]
        prior = local_items.get(name)
        if prior is None and codename:
            prior = local_items.get(by_code.get(codename.lower(), ""))
        if prior is None:
            added.append(name)
            merged.append({
                "name": name, "codename": codename, "key": key,
                "aliases": list(dict.fromkeys([name] + official_aliases)),
            })
            continue
        aliases = list(dict.fromkeys(
            [str(a).strip() for a in (prior.get("aliases") or []) if str(a).strip()]
            + [name] + official_aliases
        ))
        new_code = codename or str(prior.get("codename") or "")
        new_key = key or str(prior.get("key") or "")
        if new_code != str(prior.get("codename") or "") or new_key != str(prior.get("key") or ""):
            updated += 1
        merged.append({"name": prior.get("name") or name, "codename": new_code,
                       "key": new_key, "aliases": aliases})

    # 官网没列、但本地有的（下架 / 改名）→ **保留**，别让用户已有的 Mod 突然识别不出来
    seen = {item["name"] for item in merged}
    for name, item in local_items.items():
        if name not in seen:
            merged.append(item)

    payload = dict(local)
    payload.update({
        "schema_version": int(local.get("schema_version") or 2),
        "source": SOURCE_URL,
        "fetched_at": str(official.get("fetched_at") or time.strftime("%Y-%m-%d")),
        "official_count": int(official.get("total") or len(official.get("characters") or [])),
        "characters": merged,
    })
    return {"payload": payload, "added": added, "updated": updated}


# ---------------------------------------------------------------- 状态文件
# ⚠️ 实现已收敛到 `fsutil.read_json` / `fsutil.write_json`（2026-10-04）——
# 与 alerts.py / sbm_data_sync.py 原先那三份逐字节相同的实现合并成一份。
def _read_json(path: Path) -> dict[str, Any]:
    from . import fsutil

    return fsutil.read_json(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    from . import fsutil

    try:
        fsutil.write_json(path, payload)
    except OSError:
        pass


def _aliases_of(item: dict[str, Any]) -> list[str]:
    return [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]


def combine_tables(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """把两张角色表按角色合并，**aliases 取并集**（primary 的字段优先）。

    为什么要合并（2026-10-01 用户要求「中文拼音也要自动识别」）：拼音别名是
    `scripts/gen_character_pinyin.py` 固化进**随包表**的，而运行时优先读的是
    `<数据根>\\runtime\\_state\\characters.json`（启动时从官网同步来的那份）。
    老用户升级前就已经有运行时表了 —— 直接以它为准会把随包表里的拼音别名**整份丢掉**，
    于是"拼音识别"在他们的机器上等于没做。两边合并后：官网的 codename 与随包的拼音都在。
    """
    if not primary.get("characters"):
        return secondary
    if not secondary.get("characters"):
        return primary

    by_name = {str(i.get("name") or "").strip(): i for i in secondary["characters"]}
    by_code = {str(i.get("codename") or "").strip().lower(): i
               for i in secondary["characters"] if str(i.get("codename") or "").strip()}

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in primary["characters"]:
        entry = dict(item)
        name = str(entry.get("name") or "").strip()
        seen.add(name)
        other = by_name.get(name)
        if other is None:
            code = str(entry.get("codename") or "").strip().lower()
            other = by_code.get(code) if code else None
        if other is not None:
            entry["aliases"] = list(dict.fromkeys(_aliases_of(entry) + _aliases_of(other)))
        merged.append(entry)

    for item in secondary["characters"]:
        name = str(item.get("name") or "").strip()
        if name and name not in seen:
            merged.append(dict(item))

    payload = dict(secondary)
    payload.update({"characters": merged})
    # primary（随包表）里的元信息若有更新，保留其来源标注
    for key in ("source",):
        if primary.get(key):
            payload[key] = primary[key]
    return payload


def _load_local(config: Any) -> dict[str, Any]:
    """本地表：**随包表与运行时表合并**（别名取并集）。

    只取运行时那份会让随包表里的拼音别名失效；只取随包那份又会丢掉官网同步来的
    新角色 —— 所以两张表都要。
    """
    from . import core

    bundled = _read_json(core.CHARACTERS_JSON)
    updated = _read_json(latest_path(config))
    if not updated.get("characters"):
        return bundled
    return combine_tables(bundled, updated)


# ---------------------------------------------------------------- 对外小工具（脚本用）
def load_local(config: Any) -> dict[str, Any]:
    """读当前生效的本地表（公开包装，供 `scripts\\fetch_characters.py` 用）。"""
    return _load_local(config)


def write_latest(config: Any, payload: dict[str, Any]) -> Path:
    """把合并后的表写到数据根，并让 core 立刻优先读它。"""
    path = latest_path(config)
    _write_json(path, payload)
    try:
        from . import core

        core.set_characters_override(path)
    except Exception:  # noqa: BLE001
        pass
    return path


def write_bundled(payload: dict[str, Any]) -> Path | None:
    """把合并后的表写回**随包那份**（发版前更新用；先备份成 `.bak-<时间戳>`）。"""
    import shutil

    from . import core

    target = core.CHARACTERS_JSON
    try:
        if target.is_file():
            shutil.copy2(target, target.with_name(target.name + time.strftime(".bak-%Y%m%d-%H%M%S")))
        _write_json(target, payload)
    except OSError:
        return None
    return target


# ---------------------------------------------------------------- 入口
def sync(config: Any, *, force: bool = False, write: bool = True,
         log: Callable[[str], None] | None = None, timeout: int = 25) -> dict[str, Any]:
    """检查官网角色表并按需更新（默认 24 小时内不重复请求、失败静默）。

    返回 ``{"ok", "skipped", "total", "added", "updated", "changed", "message"}``：
    调用方（后台预热 / CLI 脚本）据此决定要不要写日志或提示，**任何失败都不该影响启动**。
    """
    now = time.time()
    cache = _read_json(cache_path(config))
    if not force and cache.get("at") and (now - float(cache["at"] or 0)) < CACHE_TTL:
        return {"ok": True, "skipped": True, "total": int(cache.get("total") or 0),
                "added": [], "updated": 0, "changed": False,
                "message": f"{int(CACHE_TTL / 3600)} 小时内已检查过"}

    try:
        official = fetch_official(timeout=timeout)
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        _write_json(cache_path(config), {"at": int(now), "ok": False, "error": str(exc)[:200]})
        _log(log, f"角色表检查失败（不影响使用）: {exc}")
        return {"ok": False, "skipped": False, "total": 0, "added": [], "updated": 0,
                "changed": False, "message": str(exc)}

    local = _load_local(config)
    merged = merge_payload(local, official)
    changed = bool(merged["added"]) or int(merged["updated"]) > 0
    if write and changed:
        _write_json(latest_path(config), merged["payload"])
        try:
            from . import core

            core.set_characters_override(latest_path(config))
        except Exception:  # noqa: BLE001
            pass
        _log(log, f"角色表已更新：新增 {len(merged['added'])} 位"
                  f"（{', '.join(merged['added'][:6]) or '无'}），共 {len(merged['payload']['characters'])} 位")
    total = int(official.get("total") or len(official.get("characters") or []))
    _write_json(cache_path(config), {"at": int(now), "ok": True, "total": total,
                                     "added": merged["added"], "changed": changed})
    return {
        "ok": True, "skipped": False, "total": total,
        "official_count": total, "local_count": len(merged["payload"]["characters"]),
        "added": merged["added"], "updated": int(merged["updated"]), "changed": changed,
        "message": ("已更新" if changed else "已是最新"),
    }
