"""Mod 下载：粘贴网址 → 并行下到临时目录 → 能解压的自动解压进库。

用户 2026-10-02 原话：「在 mod 库页按钮下面加一个 mod 下载，**下载进临时文件夹**，
**能解压的解压进库**，**不能解压的提示用户需要手动解压**，**并行多线程下载**」，
并明确下载源 = **「给个输入框输入网址」**（不是内置清单）。

设计要点：
* **下载**走 `fastnet`（经 `dependencies._http_get`）—— 它在慢/抖时**临时**启并发分块、
  直连不通时**临时**换镜像线路，用完即放，不留后台线程、不改系统；
* **落地目录** = `<数据根>\\runtime\\downloads\\`（临时文件夹，不直接写 Mod 库）；
* **解压/入库**复用 `api._import_archive_file()`（含 zip-slip 校验、自动提层、重名加后缀、
  收编与角色识别）—— 那条链路是拖入 zip 用过的、已验证的，**不另写一套**；
* 解压不了（非 zip/7z/rar，或包本身坏了）→ **不清掉文件**，标成「需手动解压」并把路径给用户。
"""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import dependencies
from . import fastnet

# 能自动解压的格式 —— **必须与 `api.IMPORT_SUFFIXES` 保持一致**
# （拖入导入支持的格式就是这几种；两边不一致会出现"拖入能导入、下载却说不能解压"）
EXTRACTABLE_SUFFIXES: tuple[str, ...] = (".zip", ".7z", ".rar")

Progress = Callable[[int, int], None] | None


def downloads_dir(config) -> Path:
    """下载落地目录（临时文件夹）：`<数据根>\\runtime\\downloads`。"""
    return Path(config.runtime_path) / "downloads"


def parse_urls(text: str | Iterable[str]) -> list[str]:
    """从输入框文本里挑出合法链接（一行一个；也容忍空格/逗号分隔），去重且保持顺序。

    只接受 `http` / `https` —— 别的协议（`file:` / `ftp:` …）一律丢掉，
    免得"下载"变成"从本机任意路径取文件"。
    """
    if not isinstance(text, str):
        text = "\n".join(str(item) for item in text)
    found: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[\s,]+", text.strip()):
        candidate = raw.strip().strip("<>\"'")
        if not candidate:
            continue
        parsed = urllib.parse.urlsplit(candidate)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        found.append(candidate)
    return found


def suffix_of(name: str) -> str:
    return Path(name).suffix.lower()


def is_extractable(name: str) -> bool:
    return suffix_of(name) in EXTRACTABLE_SUFFIXES


# 按**内容**认压缩包（很多下载地址根本不含文件名 —— 香蕉网的 `/dl/<id>` 就是纯数字）。
# 现场（用户 2026-10-02）：`https://gamebanana.com/dl/1820618` 下回来 6.9 MB，
# 前 8 字节是 `Rar!\x1a\x07\x01\x00`（RAR5），却因为文件名叫 `1820618` 没有后缀，
# 被判成「需手动解压」—— **整个包白下了**。
_MAGIC_SUFFIXES: tuple[tuple[bytes, str], ...] = (
    (b"Rar!\x1a\x07\x01\x00", ".rar"),     # RAR5
    (b"Rar!\x1a\x07\x00", ".rar"),         # RAR4
    (b"PK\x03\x04", ".zip"),               # ZIP
    (b"PK\x05\x06", ".zip"),               # 空 ZIP
    (b"7z\xbc\xaf\x27\x1c", ".7z"),
    (b"\x1f\x8b", ".gz"),
)


def sniff_suffix(path: Path) -> str:
    """读文件头，认出真正的压缩格式；认不出返回空串。"""
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return ""
    for magic, suffix in _MAGIC_SUFFIXES:
        if head.startswith(magic):
            return suffix
    return ""


def ensure_known_suffix(path: Path) -> Path:
    """后缀不认识但**内容认识** → 改名补上后缀（否则会被判「需手动解压」）。

    只加后缀、不动内容；改名失败就原样返回（不为了个名字把结果搞砸）。
    """
    path = Path(path)
    if path.suffix.lower() in EXTRACTABLE_SUFFIXES:
        return path
    suffix = sniff_suffix(path)
    if not suffix or suffix not in EXTRACTABLE_SUFFIXES:
        return path
    target = unique_path(path.parent, path.name + suffix)
    try:
        path.rename(target)
    except OSError:
        return path
    return target


def file_name_from(url: str) -> str:
    """从 URL 末段推断落盘文件名（去掉 query、还原 %xx、清掉非法字符）。

    推不出名字（末段为空或只有 `/`）时给 `mod_<8位hash>`，没有后缀 ⇒ 会被判成
    "需手动解压"，让用户自己看 —— 不猜、也不假装认识。
    """
    import hashlib

    path = urllib.parse.urlsplit(url).path
    last = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    last = re.sub(r'[\\/:*?"<>|]+', "_", last).strip(" .")
    if not last:
        last = "mod_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    if len(last) > 120:                     # 超长名（有些 CDN 会塞很长的签名段）
        stem, dot, ext = last.rpartition(".")
        keep = stem[:100]
        last = f"{keep}.{ext}" if dot else keep
    return last


def unique_path(directory: Path, name: str) -> Path:
    """在同一目录里挑一个不冲突的落盘路径（`a.zip` → `a_2.zip`）。"""
    dest = Path(directory) / name
    counter = 1
    while dest.exists():
        counter += 1
        stem, dot, ext = name.rpartition(".")
        dest = Path(directory) / (f"{stem}_{counter}.{ext}" if dot else f"{name}_{counter}")
    return dest


def looks_like_slow(error: str) -> bool:
    """这条报错是不是"网太慢/连不上"那一类？

    现场（用户 2026-10-02 实测，日志原文）：
    ``所有线路都失败 → 直连: 探测速度仅 0.01 MB/s（低于 0.3 MB/s 可用线），放弃这条线路``
    —— **10 KB/s 就是没开加速器的典型症状**，用户的原话是要「**弹窗建议开 vpn** 而不是纯失败」，
    所以这种失败要能被单独认出来（前端据此弹提示），不能混进"文件坏了"那类错误里。
    """
    text = (error or "").lower()
    return any(hint in text for hint in (
        "探测速度", "低于", "所有线路都失败", "放弃这条线路", "线路",
        "timed out", "超时", "timeout", "10060", "10054", "10053",
        "connection reset", "connection aborted", "远程主机强迫", "不能连接", "拒绝",
        # 被拒绝/被限流也归到"网络这条路不通"：对用户的建议同样是"开代理再试"
        # （实测 fastnet 的报错会写成 `HTTP Error 403: Forbidden` / `HTTP Error 429: …`）
        "403", "forbidden", "429", "too many requests",
    ))


def _cleanup_partial(target: Path, *, log: Callable[[str], None] | None = None) -> None:
    """失败时把半成品清掉（用户 2026-10-02：「下载失败要清理掉失败的半成品」）。

    ⚠️⚠️ **必须连分块记录（sidecar）一起删**（2026-10-04 审计发现的**数据损坏**级坑）：
    fastnet 的分块下载有两份产物 —— 工作文件 `<名字>.mcdownload` 与"哪些块已完成"的
    `<名字>.mcdownload.mcparts.json`。原实现只删了前者，于是下次重试时 sidecar 还在、
    里面记着"这些块已下好" ⇒ **跳过它们**，而工作文件是新建的空文件 ⇒ 那些区间是空洞；
    又因为块是 seek 写的、文件长度照样能到总大小 ⇒ 上层"大小相等"判据通过 ⇒
    **报成功并落位一个坏包**（rar/7z 只查文件头，坏包会静默进 Mod 库）。

    现在直接把 fastnet 认识的**全部续传产物**清掉（`fastnet.discard_partial` 是唯一真源，
    避免这里再抄一份文件名清单 —— 抄漏一个就是这个坑）。
    ⚠️ 代价：清掉续传文件后，**下次重试是从头下**（不再续传）—— 用户要的是"别留垃圾"，
    所以这里按他说的做。清理本身失败也不抛（删不掉不该让任务结果变样）。
    """
    from . import fastnet

    for path in fastnet.discard_partial(Path(target)):
        if log:
            log(f"已清理失败的半成品：{path.name}")


# Mod 下载专用的"这条线路还能不能救"阈值。
# fastnet 默认 0.3 MB/s（给 GitHub 组件用的 —— 那边有镜像可换，极慢就该换线路）；
# 而 Mod 下载面对的是**没有镜像**的站点（香蕉网等），判死就等于用户下不到东西。
# 实测（用户 2026-10-02，开 VPN）：探测只有 **0.036 MB/s**，而实际能跑到 **0.229 MB/s**
# —— 探测值明显偏低（首字节延迟占大头），拿它判死会误杀。所以这里**干脆不判死**：
# 慢就慢慢下（有进度条、可以取消），至少文件能下完。
MOD_DOWNLOAD_DEAD_MBPS = 0.0

# 长时间没有任何数据往来就判定"卡死"（秒）。用户 2026-10-02 实测遇到任务永远挂着
# "下载中"、进度 0/0、也没速度 —— 界面必须能自己收尾。5 分钟是"零字节增长"的阈值，
# 正常慢速下载（实测 0.12~0.23 MB/s）每几秒就会有字节进来，不会误伤。
MOD_DOWNLOAD_STALL_SECONDS = 300


def download(url: str, dest_dir: Path, *, progress: Progress = None,
             timeout: int = 600, log: Callable[[str], None] | None = None,
             name: str = "", parallel: bool | None = None,
             cancel=None, keep_partial: bool = False) -> tuple[Path | None, str, bool]:
    """把 `url` 下到 `dest_dir`；返回 `(路径, 错误信息, 是否"网太慢/连不上")`。

    走 `dependencies._http_get` → `fastnet.download`：慢时自动并发分块、直连不通自动换镜像，
    断点续传（`.mcdownload` 临时文件）与 sha256 校验都在那条链路里，**这里不重复实现**。

    *name* = **已知的真实文件名**（香蕉网 API 里的 `_sFile`）—— 下载地址本身常常不含文件名
    （`/dl/1820618`），用上报来的名字才不会落成"一个没有后缀的数字"。下完还会**按内容
    再校一次后缀**（见 `ensure_known_suffix`）。

    第三个返回值是给前端用的：**"慢到被 fastnet 放弃"要提示开 VPN，而不是只说失败**。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = unique_path(dest_dir, name or file_name_from(url))
    # ⚠️ **「香蕉网高速下载」（2026-10-03 用户要求：「香蕉网高速下载逻辑也加进去」）**。
    #
    # 并发对**慢线路**收益极大（今天三组实测）：
    #     无 VPN 直连香蕉网  单连接 0.008 MB/s ／ 4 连接 0.034 ／ 16 连接 0.104（13 倍）
    #     开 VPN            单连接 0.129 MB/s ／ 4 连接 0.090 ／ 16 连接 0.641（5 倍）
    # 两次都是"4 条不够、十几条才吃满"，所以 Mod 下载**默认就强上并发**。
    #
    # 但要**尊重用户的开关**（设置页「下载与网络 → 下载加速」三个档）：
    #   * `never`  → 走单连接（用户明确关了加速）；
    #   * `always` → 直接并发；
    #   * `auto`   → 也走并发 —— 因为"自动"的语义就是"慢时并发"，而香蕉网**没有镜像可换**，
    #                `auto` 在这里唯一的后果就是"探测到慢就放弃并发"，正好把最该并发的场景排掉。
    # 调用方显式传 `parallel=False`（比如用户在这里单独关掉）同样退回单连接。
    #
    # `policy="always"` 还会**跳过"判死线路"**那一步（`_attempt_line` 里 `policy != "always"`
    # 才判死）—— 香蕉网没镜像，判死没有意义；去留交给 fastnet 的**试用窗口**：
    # 上并发先跑 12 秒，实测没比单连接快就自己切回去。
    try:
        _user_policy = fastnet.get_policy()
    except Exception:  # noqa: BLE001
        _user_policy = "auto"
    _policy = "never" if (parallel is False or _user_policy == "never") else "always"
    try:
        dependencies._http_get(
            url, target, timeout=timeout, chunk_callback=progress, log=log,
            policy=_policy,
            # **不判死**：Mod 下载面对的是没有镜像可换的站点，慢也该下完（见上面常量说明）
            dead_mbps=MOD_DOWNLOAD_DEAD_MBPS,
            cancel=cancel,
        )
    except fastnet.Cancelled:
        # 用户点了「终止」/「暂停」（用户 2026-10-02 要求这两个按钮）：
        # **暂停保留半成品**（`.mcdownload` / `.parts`）以便「继续」时断点续传；
        # **终止则清干净**，不留垃圾。
        if not keep_partial:
            _cleanup_partial(target, log=log)
        if log:
            log(f"下载已{'暂停（保留断点）' if keep_partial else '终止'}：{target.name}")
        return None, ("已暂停" if keep_partial else "已终止"), False
    except Exception as exc:  # noqa: BLE001 —— 网络/校验/磁盘，一律如实回报
        message = str(exc)
        _cleanup_partial(target, log=log)      # 失败不留半成品
        if log:
            log(f"下载失败 {url}：{message}")
        return None, message, looks_like_slow(message)
    renamed = ensure_known_suffix(target)
    if renamed != target and log:
        log(f"按内容识别为 {renamed.suffix}：{target.name} → {renamed.name}")
    target = renamed
    if log:
        log(f"下载完成 {target.name}（{target.stat().st_size} B）")
    return target, "", False


DOWNLOAD_INFO_NAME = "download-info.json"


def write_download_info(
    mod_dir: Path,
    *,
    source_url: str = "",
    file_url: str = "",
    file_name: str = "",
    title: str = "",
    author: str = "",
    version: str = "",
    game: str = "",
    page: str = "",
    site: str = "",
    site_category: str = "",
) -> Path | None:
    """往**这个 Mod 自己的文件夹**里写一份「从哪下的、什么时候下的」。

    用户 2026-10-02 原话：「还有每个 mod 文件夹内都要保存下载地址、时间这些信息」。
    键名用中文、值保持原样 —— 这份文件是**给人看的**（出问题时能一眼看出这个包是哪个版本、
    从哪个页面来的），不是给程序读的配置。文件名沿用项目里 `mod.meta.json` 那种英文小写风格。

    只写这一个文件，**不动目录里其它任何东西**；写失败不影响入库结果。
    """
    import datetime
    import json

    mod_dir = Path(mod_dir)
    if not mod_dir.is_dir():
        return None
    payload: dict[str, str] = {
        "下载时间": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if source_url:
        payload["来源网址"] = source_url          # 用户粘进来的那个（香蕉网常是页面地址）
    if file_url:
        payload["文件网址"] = file_url            # 实际下载的直链
    if file_name:
        payload["文件名"] = file_name
    if site:
        payload["站点"] = site
    if title:
        payload["标题"] = title
    if author:
        payload["作者"] = author
    if version:
        payload["版本"] = version
    if game:
        payload["所属游戏"] = game
    if page:
        payload["页面"] = page
    if site_category:
        # 香蕉网的网站分类（如 `Skins / Operators / Arcane`）—— 用户 2026-10-04 要求接进来。
        # 这份文件是给人看的（中文键、值原样），所以只写这一行可读路径；
        # 机器读的那份（含 root=皮肤/UI 判定）写在 `mod.meta.json` 里，见 api 的入库流程。
        payload["网站分类"] = site_category
    target = mod_dir / DOWNLOAD_INFO_NAME
    try:
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return None
    return target


def summarize(items: Sequence[dict]) -> dict:
    """把任务列表汇总成给前端的计数块。"""
    counts = {"total": len(items), "downloading": 0, "imported": 0, "manual": 0, "failed": 0}
    for item in items:
        status = item.get("status", "")
        if status in ("等待中", "下载中"):
            counts["downloading"] += 1
        elif status == "已入库":
            counts["imported"] += 1
        elif status == "需手动解压":
            counts["manual"] += 1
        elif status == "失败":
            counts["failed"] += 1
    return counts


# ── 香蕉网（GameBanana）适配 ─────────────────────────────────────────────────
# 用户 2026-10-02 原话：「我还要对香蕉网做适配，你看看能不能看到网址是香蕉网，比如
# https://gamebanana.com/mods/721442，就**拉取资源同时拉取一张图片**，然后**如果访问不上，
# 就弹窗提示无法访问，建议检查 vpn**」。
#
# 为什么走 **apiv11 而不是抓网页**：那个页面是前端渲染的，HTML 里没有直接的下载地址；
# 而 `apiv11/Mod/<id>/ProfilePage` 一次就给全 —— 真实文件名、每个文件的下载直链、
# 封面图、所属游戏（可以顺手校验"这是不是终末地的 Mod"）、作者、版本、点赞数。
GAMEBANANA_API = "https://gamebanana.com/apiv11/Mod/{mod_id}/ProfilePage"
# 只认 **Mod 页面**地址；`/dl/<id>` 是**文件直链**（本来就指向文件），当普通链接下即可 ——
# 拿文件 id 去查 Mod API 只会 404，会把一个好链接误报成"访问不上"。
_GAMEBANANA_PATH_RE = re.compile(r"^/mods/(?:download/)?(\d+)(?:/|$)")
EXTRA_TIMEOUT = 25


class GameBananaUnreachable(RuntimeError):
    """访问不上香蕉网（超时 / DNS / 证书 / 被地区限制）—— 调用方据此提示"检查 VPN"。"""


def gamebanana_id(url: str) -> int | None:
    """认得香蕉网的 **Mod 页面**地址就返回 Mod id，否则 None。

    支持的形态（实测这两种都能在站点里复制到）：
      * `https://gamebanana.com/mods/721442`
      * `https://gamebanana.com/mods/download/721442`

    ⚠️ `https://gamebanana.com/dl/<文件id>` **不算** —— 那是文件直链，本来就指向文件，
    当普通链接下载即可；拿文件 id 去查 Mod API 只会 404，把好链接误报成"访问不上"。
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "gamebanana.com":
        return None
    match = _GAMEBANANA_PATH_RE.match(parsed.path or "")
    return int(match.group(1)) if match else None


# ⚠️ 小于这个大小的文件视为**配套小文件**（作者单独发的 `_Core.ini` / 补丁 ini 之类）。
# 很多 Mod 的「主包 + 配套」是**分开的文件**，只下主包会缺关键 ini、装上去毫无效果
#（2026-10-03 实测：CharacterChange 1.3.1 缺 `_Core.ini`，作者在 Read me 里明写需要它，
#  而它作为 `_core_2.zip`(275 B) 单独挂在同一个 Mod 页面上）。
AUX_FILE_MAX_BYTES = 2 * 1024 * 1024

# 更新记录（Updates）接口 —— **"这一版需要下什么"的权威来源**。
# 用户 2026-10-04 原话：「香蕉网的下载逻辑有问题，应该先去
# https://gamebanana.com/mods/updates/690864 ，看**最新版需要下什么资源**，然后再去下载，
# 而不是一上来就下最新的包」。
GAMEBANANA_UPDATES_API = "https://gamebanana.com/apiv11/Mod/{mod_id}/Updates"

# ── 网站分类（"这是皮肤还是 UI"）─────────────────────────────────────────────
# 用户 2026-10-04 要求：「把 mod 在香蕉网中的分类接入管理器的分类」。
#
# 实测（2026-10-04，把终末地全部 **695** 个 Mod 拉下来逐条统计）：
#   * `Mod/<id>/ProfilePage` 给 `_aCategory`（叶子 / 直接分类）与 `_aSuperCategory`
#     （它的父级，**可以为空**）；列表与搜索接口反而直接给根分类 `_aRootCategory`。
#   * 终末地只有三个**根**分类：Skins(35464) / UI(42706) / Other-Misc(42780)，
#     而且 **100% 的 Mod 都带分类**（没有"未分类"漏网）。
#   * ⚠️ **光看 `_aSuperCategory` 定不了根**：UI 与 Other/Misc 类 Mod 的 super 是空的，
#     而 `Skins → Operators → 角色` 的 super 是 `Operators`(42770) 而不是 `Skins`。
#   * ⚠️ **别硬编码叶子 id**：它们会随新角色增长（Arcane 47395 / Liino 48075 /
#     Typhoeus 48868 都是后加的）。所以只硬编码 3 个根，其余靠"根的直接子分类"映射回去。
GAMEBANANA_ROOT_CATEGORIES = {35464: "Skins", 42706: "UI", 42780: "Other/Misc"}
GAMEBANANA_SKINS_CHILDREN = {42770, 42771, 42772, 42778, 42779}


def _gb_category_entity(value) -> tuple[int, str]:
    """把 API 里 `{_idRow, _sName, …}` 那种分类对象拆成 `(id, 名字)`。

    不是对象（缺失 / null / 空字典）时返回 `(0, "")` —— 实测 UI 与 Other/Misc 类 Mod
    的 `_aSuperCategory` 就是这种"有键但没内容"的形态，别把它当成名字为空的分区。
    """
    if not isinstance(value, dict):
        return 0, ""
    try:
        ident = int(value.get("_idRow") or 0)
    except (TypeError, ValueError):
        ident = 0
    return ident, str(value.get("_sName") or "").strip()


def gamebanana_category(data: dict) -> dict:
    """从 ProfilePage 数据里取**网站分类**，返回可直接展示与存档的结构。

    返回 `{"id", "name", "super_id", "super_name", "root", "path"}`：
      * `root` = `Skins` / `UI` / `Other/Misc`（定不了就是 `""`，不猜）；
      * `path` = 给人看的完整路径，如 `Skins / Operators / Arcane`、`UI`。

    ⚠️ 这是**作者投稿时自己选的**分类，是辅助判据 —— 不拿它覆盖文件内容/ini 解析的结论
    （实例：RabbitFX 挂在 Other/Misc 里，但它其实是配套依赖）。
    """
    cat_id, cat_name = _gb_category_entity(data.get("_aCategory"))
    sup_id, sup_name = _gb_category_entity(data.get("_aSuperCategory"))

    root = GAMEBANANA_ROOT_CATEGORIES.get(cat_id) or GAMEBANANA_ROOT_CATEGORIES.get(sup_id) or ""
    if not root and (cat_id in GAMEBANANA_SKINS_CHILDREN or sup_id in GAMEBANANA_SKINS_CHILDREN):
        root = "Skins"

    parts: list[str] = []
    for value in (root, sup_name, cat_name):
        if value and value not in parts:
            parts.append(value)          # UI 类 Mod 的叶子名就是根名，这里天然去重
    return {
        "id": cat_id,
        "name": cat_name,
        "super_id": sup_id,
        "super_name": sup_name,
        "root": root,
        "path": " / ".join(parts),
    }


def _plain_text(value: str, limit: int = 400) -> str:
    """把更新说明的 HTML 压成一行纯文本（只用于在界面上展示"这一版改了什么"）。"""
    import html as _html

    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.I)
    text = re.sub(r"</(?:p|li|ul|div)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", " ", text)
    return text.strip()[:limit]


def gamebanana_updates(mod_id: int, *, timeout: int = EXTRA_TIMEOUT,
                       cancel=None) -> list[dict]:
    """取一个 Mod 的**更新记录**（最新在前）；取不到就返回空列表（绝不影响下载主流程）。

    实测（mod 690864，2026-10-04）：
        最新那条 update 的 `_aFileRowIds = [1813631, 1809855]`
        精确对应 `changescreens_182.zip`(957 MB 主包) + `_core_2.zip`(275 B 补丁)
    —— 这正是"最新版需要哪些资源"。而按"未归档里挑最新/最大"只是**猜**：
    作者把补丁单独挂着、或旧版包比新版大时就会挑错（本项目真踩过：下到 1.3.1 旧版，
    而必需的 `_Core.ini` 从来没被下载过）。

    单条记录的字段：`_idRow`(update id) / `_sVersion` / `_sName` / `_tsDateAdded` /
    `_sText`(HTML 说明) / `_aFileRowIds`(关联的文件 id) / `_aFiles`(作者随帖上传的文件)。
    """
    import json

    from . import dependencies, fastnet

    url = GAMEBANANA_UPDATES_API.format(mod_id=mod_id)
    try:
        raw = dependencies._http_get(url, timeout=timeout, cancel=cancel)
    except fastnet.Cancelled:
        raise                           # 用户点的暂停/终止，原样抛给上层
    except Exception as exc:  # noqa: BLE001 —— **更新记录拿不到不该让整次下载失败**
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return []
    if not isinstance(data, dict):
        return []
    records: list[dict] = []
    for record in data.get("_aRecords") or []:
        if not isinstance(record, dict):
            continue
        try:
            record_id = int(record.get("_idRow") or 0)
        except (TypeError, ValueError):
            record_id = 0
        file_ids: list[int] = []
        for value in record.get("_aFileRowIds") or []:
            try:
                file_ids.append(int(value))
            except (TypeError, ValueError):
                continue
        records.append({
            "id": record_id,
            "version": str(record.get("_sVersion") or ""),
            "name": str(record.get("_sName") or ""),
            "added": int(record.get("_tsDateAdded") or 0),
            "text": _plain_text(record.get("_sText") or ""),
            "file_ids": file_ids,
            "files": [str(f.get("_sFile") or "") for f in (record.get("_aFiles") or [])
                      if isinstance(f, dict)],
        })
    # 最新在前（`_aRecords` 本来就是，但别依赖这个隐含顺序）
    records.sort(key=lambda item: item["added"], reverse=True)
    return records


def split_mod_files(files: list[dict],
                    required_ids: Sequence[int] | None = None) -> tuple[dict | None, list[dict]]:
    """从文件列表里挑出**主包**，并把**需要一起下的其它文件**返回。

    优先口径（用户 2026-10-04 要求）—— *required_ids* = **最新更新记录里列出的文件 id**：
    给了它就**只认这些**（"这一版需要什么就下什么"），主包 = 其中最大的那个，
    其余全部作为配套一起下。这比"猜"准确：作者把补丁单独挂着时不会再漏，
    也不会把同页面**别的模块**的大包（例如同页的 CharacterChange 86 MB）顺手拖下来。

    退回口径（没有更新记录的老 Mod / 更新接口取不到时）：
    * **主包** = 未归档的中**最新**那个（按 `_tsDateAdded`）——
      不能取"列表第一个"：API 的 `_aFiles` **不是**按时间排的，
      实测那个 Mod 把 1.3.1(86 MB) 排在 1.8.2(957 MB) 前面，取第一个就下到了旧版。
    * **配套** = 其余未归档的**小文件**（< 2 MB），下载完主包后自动一起下。
    """
    live = [f for f in files if not f.get("archived")]
    pool = live or list(files)
    if not pool:
        return None, []
    if required_ids:
        wanted = {int(value) for value in required_ids}
        picked = [f for f in pool if f.get("id") in wanted]
        if picked:
            main = max(picked, key=lambda f: (f.get("size") or 0))
            return main, [f for f in picked if f is not main]
    big = [f for f in pool if not f.get("aux")]
    main_pool = big or pool
    main = max(main_pool, key=lambda f: (f.get("added") or 0, f.get("size") or 0))
    aux = [f for f in pool if f is not main and f.get("aux")]
    return main, aux


def gamebanana_profile(mod_id: int, *, timeout: int = EXTRA_TIMEOUT, cancel=None) -> dict:
    """取一个 Mod 的元数据（含真实下载直链与封面图）。

    访问不上时抛 `GameBananaUnreachable` —— **这条是给用户看的**（"检查 VPN"），
    所以不要把底层异常原样丢出去。

    *cancel* = 用户点了「暂停 / 终止」时的判据（2026-10-04 加，用户实测报的问题）：
    这个请求最长要等 25 秒，而原来**探测期间完全不检查暂停/终止** ⇒ 他的感受是
    「**探测期间无法暂停**」「**点了终止也还是探测中**」。现在把 cancel 一路传进
    `_http_get`（fastnet 在数据块边界会中断），中断时**原样抛 `fastnet.Cancelled`** ——
    那不是"访问不上"，上层要按"用户停的"来收尾，不能报成网络错误。
    """
    import json

    from . import dependencies, fastnet

    url = GAMEBANANA_API.format(mod_id=mod_id)
    try:
        raw = dependencies._http_get(url, timeout=timeout, cancel=cancel)
    except fastnet.Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001 —— 网络层各种异常统一成"访问不上"
        raise GameBananaUnreachable(str(exc)) from exc
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except (ValueError, AttributeError) as exc:
        raise GameBananaUnreachable(f"返回的不是有效数据：{exc}") from exc
    if not isinstance(data, dict):
        raise GameBananaUnreachable("返回的不是有效数据")

    cover = ""
    for image in ((data.get("_aPreviewMedia") or {}).get("_aImages") or []):
        base = (image.get("_sBaseUrl") or "").rstrip("/")
        name = image.get("_sFile530") or image.get("_sFile220") or image.get("_sFile")
        if base and name:
            cover = f"{base}/{name}"
            break

    files: list[dict] = []
    for entry in list(data.get("_aFiles") or []) + list(data.get("_aArchivedFiles") or []):
        link = entry.get("_sDownloadUrl") or ""
        if link:
            files.append({
                # ⚠️ **文件 id 必须带上**（2026-10-04）：更新记录的 `_aFileRowIds` 就是靠它
                # 和这里对上的 —— 有了它才能按"最新版需要哪些资源"精确下载。
                "id": int(entry.get("_idRow") or 0),
                "file": entry.get("_sFile") or "",
                "size": int(entry.get("_nFilesize") or 0),
                "url": link,
                # ⚠️ **必须带上时间戳**（2026-10-03 修）：API 的 `_aFiles` **不是**按时间排的，
                # 之前"取第一个未归档的"会挑到旧版 —— 实测那个 Mod 的列表是
                # 1.3.1(86MB) / _core_2 / _core_ffd68 / 1.8.2(957MB)，取第一个就下了 1.3.1。
                "added": int(entry.get("_tsDateAdded") or 0),
                # 配套小文件（作者单独发的 `_Core.ini` 这类）：主包缺它不工作，
                # 所以要能识别出来一并下载。
                "aux": bool(entry.get("_nFilesize") is not None and int(entry.get("_nFilesize") or 0) < AUX_FILE_MAX_BYTES),
                "version": entry.get("_sVersion") or "",
                "archived": bool(entry.get("_bIsArchived")),
            })
    if not files:
        raise GameBananaUnreachable("这个页面里没有可下载的文件")

    # ── **"这一版需要什么资源"：以最新更新记录为准**（用户 2026-10-04 要求）──────────
    # 拿最新那条 update 的 `_aFileRowIds`（它列出的就是这一版关联的文件），
    # 映射到上面的 `files`；映射不到的（作者已删/归档）如实记下来，别静默当没有。
    latest_update: dict = {}
    required_ids: list[int] = []
    missing: list[int] = []          # ⚠️ 必须在分支外初始化（否则没有更新记录时 UnboundLocalError）
    try:
        updates = gamebanana_updates(mod_id, cancel=cancel)
    except Exception:  # noqa: BLE001 —— 含用户暂停；更新记录不该让整次下载失败
        updates = []
    if updates:
        latest_update = updates[0]
        known = {f["id"] for f in files}
        required_ids = [fid for fid in latest_update.get("file_ids") or [] if fid in known]
        missing = [fid for fid in latest_update.get("file_ids") or [] if fid not in known]

    return {
        "mod_id": int(data.get("_idRow") or mod_id),
        "name": data.get("_sName") or "",
        "game": ((data.get("_aGame") or {}).get("_sName")) or "",
        "author": ((data.get("_aSubmitter") or {}).get("_sName")) or "",
        "version": data.get("_sVersion") or "",
        "likes": int(data.get("_nLikeCount") or 0),
        "page": data.get("_sProfileUrl") or f"https://gamebanana.com/mods/{mod_id}",
        "cover": cover,
        # 网站分类（作者投稿时选的："皮肤 / UI / 其它"，Skins 下还带角色名）——
        # 就是这一个字段解析出来，**不需要多发任何请求**（ProfilePage 本来就带）。
        "category": gamebanana_category(data),
        "files": files,
        # 最新更新（"这一版改了什么 + 要下哪些"）
        "latest_update": latest_update,
        "required_ids": required_ids,
        "required_missing": missing,
    }


def download_cover(url: str, dest_dir: Path, *, timeout: int = EXTRA_TIMEOUT,
                   cancel=None) -> Path | None:
    """把封面图下到临时目录；失败返回 None（**图只是锦上添花，不该让整个任务失败**）。

    *cancel*（2026-10-04 加）：封面也是一次网络请求（最长 25 秒），用户点了暂停/终止时
    同样不该卡在这里 —— 中断时直接返回 None（封面本来就是可选的，不需要报错）。
    """
    if not url:
        return None
    from . import dependencies

    name = "cover_" + file_name_from(url)
    if not Path(name).suffix:
        name += ".jpg"
    target = unique_path(Path(dest_dir), name)
    try:
        dependencies._http_get(url, target, timeout=timeout, cancel=cancel)
    except Exception:  # noqa: BLE001 —— 含 fastnet.Cancelled（用户停的，封面就不要了）
        return None
    return target

