"""
EndfieldModController PoC core.

This module intentionally uses only the Python standard library so it can be
executed in a temporary PoC directory without installing dependencies.

Design goals for this PoC:
- scan a mod library and classify character mods vs dependency/tool mods;
- parse EFMI / 3DMigoto .ini files for [Key...] sections, cycle variables and
  command-list actions;
- patch managed mod copies so the original hotkeys stop firing;
- generate a small EFMI controller mod which consumes an action queue from
  d3dx_user.ini and applies the requested action after F10;
- write d3dx_user.ini safely (atomic replace, backup);
- build an XXMI command line and environment that keeps ReShade outside the
  game directory.
"""
from __future__ import annotations

import time

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import fsutil
from . import hotkey_hints


# ---------------------------------------------------------------------------
# 「锁 Mod 热键」动作总开关 —— **2026-10-02 晚重新启用**（用户原话：
# 「还有做一下锁，那个启动页的内部 mod 菜单改成 **mod 快捷键锁定**，**默认开**，
#   解释为 **mod 间快捷键可能冲突**，上锁可以从 mod 菜单调整，避免冲突」）
#
# **它做什么**：`patch_mod_hotkeys()` 把每个 Mod（staging 副本）里 `[Key*]` 的 `key = ...`
# 统一改写成 `no_modifiers VK_F24` —— 手按原来的键不再生效，操作集中到游戏内面板。
#
# **为什么现在能开**（当天早些时候曾停用，理由已消失）：
#   * 当时停用是因为"面板要发 Mod 自己的原键，锁了键面板就没人接"；
#   * 现在面板走 **F13..F24 内部通道**（把切档逻辑注入到 Mod 自己的 ini 里，见
#     `inject_panel_lists`），**与 Mod 的 `[Key*]` 段无关** ⇒ 锁键不影响面板；
#   * 而且锁键正好治一个真问题：**多个 Mod 抢同一个真实键**（莱万汀 6 个部件都绑 `→`、
#     佩丽卡也绑 `←`…），手按时互相干扰；锁上之后只有面板能驱动，各 Mod 不再打架。
#
# **怎么关**：把这里改成 `False`（判据、代码、备份/回滚链路都原样留着）。
# ---------------------------------------------------------------------------
HOTKEY_LOCK_ENABLED = True


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EndfieldModControllerError(Exception):
    """Base class for PoC errors."""


class PathGuardError(EndfieldModControllerError):
    """Raised when a write would touch a forbidden path."""


class IniParseError(EndfieldModControllerError):
    """Raised when an ini file cannot be parsed safely."""


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def read_text(path: Path) -> str:
    """Read UTF-8 text, tolerating a UTF-8 BOM and legacy encodings."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "gbk", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_name(name: str) -> str:
    """把任意名字弄成**目录名/文件名安全**的样子。

    ⚠️ 2026-10-03 修：原来只做了一遍替换，于是组名「加载页 / 壁纸」会变成
    **`加载页 _ 壁纸`**（斜杠变下划线、两边空格原样留着）—— 既难看，又让
    `MC_加载页 _ 壁纸_xxx` 这种目录名一出现就被用户当成 bug 报上来。
    现在再压一遍空白：连续空白并成一个下划线、首尾下划线去掉。
    """
    name = re.sub(r"[^\w\-. \u4e00-\u9fff]+", "_", name.strip())
    name = re.sub(r"\s+", "_", name).strip("_")
    return name or uuid.uuid4().hex[:8]


def tsv_cell(value: object) -> str:
    """Sanitize a value for a tab-separated actions file."""
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")


def stable_id(*parts: str) -> str:
    """Return a stable numeric id that fits safely in a 3DMigoto variable."""
    raw = "".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).digest()
    value = int.from_bytes(digest[:4], "big") & 0x7FFFFFFF
    return str(value)

# ---------------------------------------------------------------------------
# Path guard
# ---------------------------------------------------------------------------

@dataclass
class PathGuard:
    """Restrict writes to known-safe roots and never touch the game directory."""

    allowed_roots: list[Path] = field(default_factory=list)
    forbidden_roots: list[Path] = field(default_factory=list)

    def _resolved(self, path: Path) -> Path:
        return path.expanduser().resolve()

    def _is_under(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def add_allowed(self, path: Path | str) -> None:
        self.allowed_roots.append(Path(path))

    def add_forbidden(self, path: Path | str) -> None:
        self.forbidden_roots.append(Path(path))

    def assert_writable(self, path: Path | str) -> Path:
        target = self._resolved(Path(path))
        for forbidden in self.forbidden_roots:
            if self._is_under(target, self._resolved(forbidden)):
                raise PathGuardError(f"Refusing to write inside game directory: {target}")
        if self.allowed_roots:
            if not any(self._is_under(target, self._resolved(root)) for root in self.allowed_roots):
                raise PathGuardError(f"Refusing to write outside allowed roots: {target}")
        return target


# ---------------------------------------------------------------------------
# INI parsing helpers
# ---------------------------------------------------------------------------

_INI_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_NAMESPACE_RE = re.compile(r"^\s*namespace\s*=\s*([^\s#;]+)", re.IGNORECASE)
_KEY_RE = re.compile(r"^\s*key\s*=", re.IGNORECASE)
_RUN_RE = re.compile(r"^\s*run\s*=\s*(.+?)\s*$", re.IGNORECASE)
_TYPE_RE = re.compile(r"^\s*type\s*=\s*(\w+)\s*$", re.IGNORECASE)
_CONDITION_RE = re.compile(r"^\s*condition\s*=\s*(.*?)\s*$", re.IGNORECASE)
_VAR_ASSIGN_RE = re.compile(r"^\s*\$([A-Za-z_\\][A-Za-z0-9_\\]*)\s*=(?!=)\s*(.*?)\s*$")
_CONST_RE = re.compile(
    r"^\s*(?P<flags>(?:(?:global|persist|locked|nopersist)\s+)*)\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*(?P<value>.*?))?\s*$",
    re.IGNORECASE,
)


@dataclass
class IniSection:
    header: str
    start_line: int          # inclusive, 0-based
    end_line: int            # exclusive, 0-based
    lines: list[str]
    preamble: list[str] = field(default_factory=list)

    @property
    def body(self) -> list[str]:
        return self.lines


@dataclass
class ConstantDecl:
    name: str
    raw_name: str
    value: str
    global_: bool = False
    persist: bool = False


def split_ini(text: str) -> tuple[list[str], list[IniSection]]:
    """Split an ini into preamble lines and sections, preserving line order."""
    lines = text.splitlines()
    preamble: list[str] = []
    sections: list[IniSection] = []
    current_header: str | None = None
    current_start: int = 0
    current_lines: list[str] = []

    def flush(end_line: int) -> None:
        nonlocal current_header, current_start, current_lines
        if current_header is not None:
            sections.append(IniSection(
                header=current_header,
                start_line=current_start,
                end_line=end_line,
                lines=current_lines[:],
            ))
        current_lines = []

    for idx, line in enumerate(lines):
        m = _INI_SECTION_RE.match(line)
        if m:
            flush(idx)
            current_header = m.group(1).strip()
            current_start = idx
            current_lines = [line]
        else:
            if current_header is None:
                preamble.append(line)
            else:
                current_lines.append(line)

    flush(len(lines))
    return preamble, sections


def parse_namespace(text: str) -> str | None:
    for line in text.splitlines():
        m = _NAMESPACE_RE.match(line)
        if m:
            return m.group(1)
        if _INI_SECTION_RE.match(line):
            break
    return None


def parse_constants(section: IniSection) -> dict[str, ConstantDecl]:
    out: dict[str, ConstantDecl] = {}
    for line in section.lines[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        m = _CONST_RE.match(line)
        if not m:
            continue
        flags = (m.group("flags") or "").lower()
        name = m.group("name")
        out[name.lower()] = ConstantDecl(
            name=name,
            raw_name=m.group("name"),
            value=(m.group("value") or "").strip(),
            global_="global" in flags,
            persist="persist" in flags,
        )
    return out


def _namespace_from_ini_path(ini_path: Path, mods_root: Path) -> str:
    """Approximate 3DMigoto's default namespace for a mod ini."""
    try:
        rel = ini_path.resolve().relative_to(mods_root.resolve())
    except ValueError:
        rel = ini_path.name
    return "\\mods\\" + str(rel).replace("/", "\\")


# ---------------------------------------------------------------------------
# Action model
# ---------------------------------------------------------------------------

@dataclass
class Action:
    id: str
    mod_id: str
    mod_name: str
    label: str
    kind: str                      # cycle | toggle | command
    ini_rel: str
    section: str
    namespace: str
    var_name: str | None = None
    values: list[str] = field(default_factory=list)
    run_command: str | None = None
    run_command_full: str | None = None
    original_keys: list[str] = field(default_factory=list)
    condition: str = ""
    source: str = ""
    target_absolute: str | None = None
    description: str = ""
    wire_id: int = 0
    targets: list[str] = field(default_factory=list)
    option_values: list[list[str]] = field(default_factory=list)
    send_index: bool = False
    # ── 统一面板用的展示字段（用户 2026-10-01：「要标明原快捷键，要自动识别那个
    #    变量的名称，推测含义」）──────────────────────────────────────────────
    hint: str = ""                              # 推测含义（中文，推不出就是空）
    var_phrase: str = ""                        # 变量名清洗后的英文短语（中文推不出时的兜底）
    key_label: str = ""                         # 原快捷键可读写法：`VK_LEFT` → `←`
    char_group: str = "未分类"                  # 角色/分组，面板按它分栏
    context_tokens: list[str] = field(default_factory=list)   # 推断用的网格/资源证据

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["values"] = list(self.values)
        d["original_keys"] = list(self.original_keys)
        d["context_tokens"] = list(self.context_tokens)
        return d


def guess_mod_description(name: str, path: Path | None = None) -> str:
    """Best-effort Chinese description for a character Mod."""
    text = name or ""
    if path is not None:
        text += " " + path.name
    pairs = [
        ("去群甲", "移除角色群甲/裙甲"),
        ("逆兔", "兔女郎风格服装与配饰"),
        ("半裸", "半裸状态服装切换"),
        ("全果", "全裸模型替换"),
        ("全裸", "全裸模型替换"),
        ("内衣", "内衣/性感服装替换"),
        ("泳装", "泳装外观替换"),
        ("JK", "JK 制服外观替换"),
        ("去面具", "移除角色面具"),
        ("去紧身衣", "移除紧身衣/紧身部件"),
        ("去裙子", "移除或缩短裙子"),
        ("更丰满", "调整角色体型/丰满度"),
        ("变肥美", "调整角色体型与曲线"),
        ("清凉", "清凉风格服装替换"),
        ("原版切换", "可在原版与 Mod 外观之间切换"),
        ("定制", "定制服装与部件切换"),
        ("写作", "身体彩绘/文字类外观替换"),
        ("尾巴", "尾巴外观或隐藏切换"),
        ("换装", "服装替换与切换"),
        ("粉毛", "头发颜色/发型修改"),
        ("猫娘", "猫娘风格装饰"),
        ("稳定版", "稳定性优先的修改版本"),
        ("多服装", "多套服装切换"),
        ("服装切换", "多套服装切换"),
    ]
    for key, desc in pairs:
        if key in text:
            return desc
    return "角色外观替换/切换"


@dataclass
class ModInfo:
    id: str
    name: str
    path: Path
    group: str = "未分类"
    kind: str = "character"        # character | dependency | tool | unknown
    conflict_group: str = ""
    # 角色归属的置信度：high = 可直接采用；low / none = 需要用户在界面上确认
    # （见 match_character_detail；用户需求「如果不确定就弹窗让用户选择」）
    char_confidence: str = "high"
    char_candidates: list[str] = field(default_factory=list)
    # **预识别**角色（用户 2026-10-01 要求「对没法完全确定归属的 Mod 进行预识别，
    # 匹配与哪个角色相关字数最多」）：只用于界面预选/预填，不改变 char_confidence ——
    # 卡片上那行黄字"角色待确认"照旧显示。
    char_guess: str = ""
    # **重复副本标注**（2026-10-01 用户要求 B）：如果库里存在另一个**内容指纹相同**的 Mod，
    # 这里记下那个 Mod 的名字（前端显示成"与「X」内容相同（重复副本）"）。
    # 只标注，**绝不自动删/自动移出** —— 去不去重由用户在界面上决定。
    duplicate_of: str = ""
    requires: list[str] = field(default_factory=list)
    source: str = ""
    source_id: str = ""
    actions: list[Action] = field(default_factory=list)
    meta_path: Path | None = None
    cover_path: Path | None = None
    source_root: Path | None = None

    @property
    def is_dependency(self) -> bool:
        return self.kind in {"dependency", "tool"}

    def to_dict(self, include_actions: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "path": str(self.path),
            "group": self.group,
            "kind": self.kind,
            "conflict_group": self.conflict_group,
            # 角色归属置信度：前端靠它决定要不要弹窗让用户确认
            # （注意这里是**显式列字段**，新增字段必须加进来，否则前端永远拿不到）
            "char_confidence": self.char_confidence,
            "char_candidates": list(self.char_candidates),
            "char_guess": self.char_guess,
            # 重复副本标注（前端卡片上显示"与「X」内容相同（重复副本）"）
            "duplicate_of": self.duplicate_of,
            "requires": list(self.requires),
            "source": self.source,
            "source_id": self.source_id,
            "cover": str(self.cover_path) if self.cover_path else "",
            "source_root": str(self.source_root) if self.source_root else "",
            "description": guess_mod_description(self.name, self.path),
        }
        if include_actions:
            data["actions"] = [a.to_dict() for a in self.actions]
        return data


# ---------------------------------------------------------------------------
# Library scanning
# ---------------------------------------------------------------------------

def load_sidecar(path: Path) -> dict[str, Any]:
    for name in ("mod.meta.json", "mod_info.json", "mod.yaml", "mod.yml"):
        candidate = path / name
        if candidate.is_file():
            text = read_text(candidate)
            if candidate.suffix == ".json":
                try:
                    data = json.loads(text)
                    return data if isinstance(data, dict) else {}
                except json.JSONDecodeError:
                    return {}
            data: dict[str, Any] = {}
            for line in text.splitlines():
                if ":" not in line or line.strip().startswith("#"):
                    continue
                k, v = line.split(":", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if not key:
                    continue
                if key in {"requires", "tags", "aliases"}:
                    data[key] = [x.strip() for x in val.strip("[]").split(",") if x.strip()]
                else:
                    data[key] = val
            return data
    return {}


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
COVER_HINTS = ("cover", "preview", "封面", "预览", "background", "背景")
COVER_DIRS = ("res", "resources", "icon", "icons", "ui")
SKIP_WALK_DIRS = {
    "textures", "texture", "meshes", "mesh", "shaderfixes", "shaders",
    "presets", "preset", "buffers", "buffer", "misc", "resources", "res",
    "ui", "tattoo", "kattextures", "hlsl", "text", "shader",
}

# 内置兜底表：characters.json 缺失或损坏时仍能工作。
# 完整表见同目录 characters.json（数据来自官网干员情报页，共 33 位）。
CHARACTER_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("管理员", ("女管理员", "管理员", "男管理员", "endministrator", "endmin")),
    ("陈千语", ("陈千语", "陈", "chengqianyu", "chen")),
    ("莱万汀", ("莱万汀", "laevatain")),
    ("佩丽卡", ("佩丽卡", "佩利卡", "perlica")),
    ("提弗洛斯", ("提弗洛斯", "typhoeus", "typhoea")),
    ("庄方宜", ("庄方宜", "zhuangfangyi", "zhuang fangyi")),
    ("洛茜", ("洛茜", "rossi")),
    ("梨诺", ("梨诺", "linuo", "liino")),
    ("洁尔佩塔", ("洁尔佩塔", "gilberta")),
    ("萤石", ("萤石", "fluorite")),
    ("赛希", ("赛希", "塞希", "塞西", "xaihi")),
    ("伊冯", ("伊冯", "yvonne")),
    ("诀", ("诀", "arcane")),
    ("余烬", ("余烬", "ember")),
    ("别礼", ("别礼", "bieli")),
    ("埃特拉", ("埃特拉", "estella")),
    ("昼雪", ("昼雪", "snowshine")),
    ("艾尔黛拉", ("艾尔黛拉", "ardelia", "小羊")),
]

CHARACTERS_JSON = Path(__file__).with_name("characters.json")
# 运行时更新的角色表（`<数据根>\runtime\_state\characters.json`，由 character_sync 从官网
# 同步）。存在就优先用它 —— exe 是 onefile，包内那份解压在临时目录里，写不进去也不持久。
CHARACTERS_OVERRIDE: Path | None = None


def set_characters_override(path: Path | None) -> None:
    """切换"更新版角色表"的位置并清缓存（character_sync 与 api 启动时各调一次）。"""
    global CHARACTERS_OVERRIDE, _CHARACTER_ALIAS_CACHE, _COMPACT_ALIAS_CACHE
    CHARACTERS_OVERRIDE = Path(path) if path else None
    _CHARACTER_ALIAS_CACHE = None
    _COMPACT_ALIAS_CACHE = None

# 角色名出现在名称前多少个字符内，才认为它是这个 Mod 的"主体"，
# 而不是括号说明文字里顺带提到的路人名（超过就降级为需要用户确认）。
LEADING_NAME_LIMIT = 12
_CHARACTER_ALIAS_CACHE: list[tuple[str, tuple[str, ...]]] | None = None


def load_character_aliases() -> list[tuple[str, tuple[str, ...]]]:
    """载入角色别名表，返回 ``[(canonical, (alias, ...)), ...]``。

    用户需求（原话）：「你找一下现在终末地全角色名，新加的 mod 要能自动匹配角色名」。
    完整数据放在同目录的 ``characters.json``（抓自官网干员情报页，33 位干员，含官网
    英文代号 codename 与美术 key）。Mod 作者通常用 codename 命名（如 ``estella``、
    ``laevatain``），所以 codename 必须进别名表。
    """
    global _CHARACTER_ALIAS_CACHE
    if _CHARACTER_ALIAS_CACHE is not None:
        return _CHARACTER_ALIAS_CACHE

    entries: list[tuple[str, tuple[str, ...]]] = []
    source = CHARACTERS_OVERRIDE if (CHARACTERS_OVERRIDE and CHARACTERS_OVERRIDE.is_file()) else CHARACTERS_JSON
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        for item in payload.get("characters", []):
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            aliases: list[str] = [name]
            for extra in (item.get("codename"), item.get("key")):
                if extra and str(extra).strip():
                    aliases.append(str(extra).strip())
            aliases.extend(str(a).strip() for a in item.get("aliases", []) if str(a).strip())
            # 去重但保持顺序（长别名优先在匹配时另行排序）
            entries.append((name, tuple(dict.fromkeys(aliases))))
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        entries = []

    _CHARACTER_ALIAS_CACHE = entries or CHARACTER_ALIASES
    return _CHARACTER_ALIAS_CACHE


def character_alias_pairs() -> list[tuple[str, str]]:
    """返回 ``[(alias_lower, canonical), ...]``，按别名长度**降序**。"""
    pairs = [
        (alias.lower(), canonical)
        for canonical, aliases in load_character_aliases()
        for alias in aliases
        if alias
    ]
    return sorted(pairs, key=lambda item: -len(item[0]))


# 紧凑化：去掉空格、下划线、连字符、点等一切分隔与标点，只留字母/数字/汉字。
# 目的（2026-10-01 用户要求「中文拼音也要自动识别」）：Mod 目录名里的拼音有各种写法 ——
# `ZhuangFangyi`、`zhuang_fang_yi`、`zhuang-fangyi`、`流萤 zhuang fang yi v2`，
# 只有把它们折叠成 `zhuangfangyi` 再比对，同一条别名才能全都命中。
_COMPACT_DROP_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_COMPACT_ALIAS_CACHE: list[tuple[str, str]] | None = None


def compact_text(text: str) -> str:
    """把文本折叠成"只有字母数字与汉字"的紧凑形式（用于拼音/下划线写法的匹配）。"""
    return _COMPACT_DROP_RE.sub("", str(text).lower())


def compact_alias_pairs() -> list[tuple[str, str]]:
    """``character_alias_pairs()`` 的紧凑版：别名同样折叠，按长度降序、去重。"""
    global _COMPACT_ALIAS_CACHE
    if _COMPACT_ALIAS_CACHE is not None:
        return _COMPACT_ALIAS_CACHE
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for alias, canonical in character_alias_pairs():
        folded = compact_text(alias)
        if not folded or folded in seen:
            continue
        seen.add(folded)
        pairs.append((folded, canonical))
    _COMPACT_ALIAS_CACHE = sorted(pairs, key=lambda item: -len(item[0]))
    return _COMPACT_ALIAS_CACHE


def guess_character(haystack: str) -> str:
    """**预识别**：说不清归属时，按"哪个角色相关字数最多"猜一个（仅供下拉预选，不代表确认）。

    用户需求（原话，2026-10-01）：「还要对一些没法完全确定归属的 Mod 进行预识别，
    就是匹配与哪个角色相关**字数最多**，比如杰哥属于洁尔佩塔，但预识别过的**还是要显示
    那个黄字无法确认归属**」。

    做法：在**紧凑串**（折叠空格/下划线/连字符，见 :func:`compact_text`）上，对每个角色
    把「命中次数 × 别名长度」累加作为"相关字数"，取最大者；并列时先看最长别名（更具体），
    再看首次出现位置（更靠前）。线索太弱（最高分 < 2，例如只命中一个单字别名）时不猜。

    返回值用途严格限定为"预选/预填"：`char_confidence` 不会被它抬高，界面上的黄色
    「角色待确认」标记照旧显示 —— 猜错会让同角色互斥失效，所以最终仍要用户点一下。
    """
    text = compact_text(haystack)
    if not text:
        return ""
    scores: dict[str, int] = {}
    longest: dict[str, int] = {}
    first_pos: dict[str, int] = {}
    for alias, canonical in compact_alias_pairs():
        if not alias:
            continue
        count = text.count(alias)
        if not count:
            continue
        scores[canonical] = scores.get(canonical, 0) + count * len(alias)
        if len(alias) > longest.get(canonical, 0):
            longest[canonical] = len(alias)
        pos = text.find(alias)
        if canonical not in first_pos or pos < first_pos[canonical]:
            first_pos[canonical] = pos
    if not scores:
        return ""
    ranked = sorted(scores.items(),
                    key=lambda kv: (-kv[1], -longest.get(kv[0], 0), first_pos.get(kv[0], 0)))
    best, best_score = ranked[0]
    return best if best_score >= 2 else ""


def match_character(haystack: str) -> str:
    """从目录名/元数据里判断属于哪个角色，返回官方中文名（无匹配返回空串）。

    规则：**出现位置靠前的优先；同一位置再比别名长度**（长的更具体）。

    2026-09-27 修正：原先只按别名长度降序取第一个命中的，结果
    「萤石去紧身衣+z键尾巴萤石去除紧身衣去尾巴（会和黎风、伊冯等角色有贴图错误）」
    被判成了「伊冯」—— 因为「萤石」和「伊冯」都是 2 字，而括号里的**说明文字**
    里出现的其它角色名被当成了主体。角色名几乎总在名称开头，所以位置优先更贴合实际。

    需要置信度（用于"不确定就弹窗让用户选"）请用 :func:`match_character_detail`。
    """
    return match_character_detail(haystack)["character"]


def match_character_detail(haystack: str) -> dict[str, Any]:
    """角色匹配 + **置信度**，供「不确定就弹窗让用户选择」使用。

    用户需求（原话）：「如果不确定就弹窗让用户选择」。

    返回::

        {
          "character": "埃特拉",           # 高置信时的判定；不确定时为空串
          "confidence": "high" | "low" | "none",
          "candidates": ["萤石", "伊冯"],   # 不确定时给用户挑的候选，按可能性排序
        }

    判定规则：

    * 没有任何角色名出现 → ``none``；
    * 只出现一个角色名且位于名称靠前处（``<= LEADING_NAME_LIMIT``）→ ``high``；
    * 只出现一个角色名但位置很靠后 → ``low``（很可能是括号/说明文字里的路人名）；
    * 出现多个角色名：第一个明显早于第二个（间隔 > 名字长度 + 余量）→ ``high``；
      否则视为分不清主次 → ``low`` 并把候选全部列出，交用户决定。

    2026-10-01（用户要求「**中文拼音也要自动识别**」）：先按**原样**匹配一遍（保持既有
    判定不变），没得到高置信时再用 :func:`compact_text` 折叠后的串匹配一遍 ——
    这样 `ZhuangFangyi`、`zhuang_fang_yi`、`zhuang-fangyi` 这类拼音写法都能认出来。

    返回里另有 ``guess``：**预识别**角色（见 :func:`guess_character`）—— 说不清归属时
    给用户一个预选，但 ``confidence`` 不变（界面上仍显示黄字"无法确认归属"）。
    """
    text = str(haystack or "")
    plain = _match_in(text.lower(), character_alias_pairs())
    if plain["confidence"] == "high":
        return {**plain, "guess": plain["character"]}

    compact = _match_in(compact_text(text), compact_alias_pairs())
    if compact["confidence"] == "high":
        return {**compact, "guess": compact["character"]}

    guess = guess_character(text)
    if plain["confidence"] == "low" or compact["confidence"] == "low":
        merged = list(dict.fromkeys(list(plain["candidates"]) + list(compact["candidates"])))
        return {"character": "", "confidence": "low", "candidates": merged, "guess": guess}
    return {"character": "", "confidence": "none", "candidates": [], "guess": guess}


def _match_in(text: str, pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """在 ``text`` 上跑一遍"位置靠前优先"的匹配（``pairs`` 已按长度降序）。"""
    hits: dict[str, int] = {}
    for alias, canonical in pairs:
        pos = text.find(alias)
        if pos < 0:
            continue
        if canonical not in hits or pos < hits[canonical]:
            hits[canonical] = pos
    if not hits:
        return {"character": "", "confidence": "none", "candidates": []}

    ordered = sorted(hits.items(), key=lambda kv: (kv[1], -len(kv[0])))
    candidates = [name for name, _ in ordered]
    first_pos = ordered[0][1]

    if len(ordered) == 1:
        if first_pos <= LEADING_NAME_LIMIT:
            return {"character": candidates[0], "confidence": "high", "candidates": candidates}
        return {"character": "", "confidence": "low", "candidates": candidates}

    second_pos = ordered[1][1]
    if first_pos <= LEADING_NAME_LIMIT and second_pos - first_pos > len(candidates[0]) + 6:
        return {"character": candidates[0], "confidence": "high", "candidates": candidates}
    return {"character": "", "confidence": "low", "candidates": candidates}


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _direct_images(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.is_file() and _is_image(p))


def has_any_ini(path: Path) -> bool:
    return any(path.rglob("*.ini"))


def direct_ini(path: Path) -> bool:
    return any(path.glob("*.ini"))


def _pick_cover_from_dir(directory: Path, owner_name: str = "") -> Path | None:
    images = _direct_images(directory)
    if not images:
        return None
    owner = owner_name.lower()
    for image in images:
        stem = image.stem.lower()
        if owner and stem == owner:
            return image
        if any(hint in stem for hint in COVER_HINTS):
            return image
    return images[0]


def find_cover(source_root: Path, mod_root: Path, meta: dict[str, Any]) -> Path | None:
    explicit = str(meta.get("cover") or meta.get("image") or "").strip()
    if explicit:
        for base in (source_root, mod_root):
            candidate = (base / explicit).resolve()
            if candidate.is_file() and _is_image(candidate):
                return candidate
    for directory in (source_root, mod_root):
        picked = _pick_cover_from_dir(directory, source_root.name)
        if picked:
            return picked
        for sub_name in COVER_DIRS:
            sub = directory / sub_name
            if sub.is_dir():
                picked = _pick_cover_from_dir(sub, source_root.name)
                if picked:
                    return picked
    return None


def infer_character_detail(
    rel_parts: Sequence[str],
    meta: dict[str, Any],
    kind: str = "",
) -> dict[str, Any]:
    """角色归属 + 置信度，供界面在「不确定」时弹窗让用户选择。

    * ``meta`` 里显式写了 ``group`` / ``character``（用户此前确认过，或 Mod 自带）→ ``high``；
    * **辅助 mod（``kind == "assist"``）直接算 ``high``**：它本来就不属于任何角色，
      不必（也不该）弹"请确认角色归属"—— 用户 2026-10-01 反馈这类小 Mod 被当成
      未识别角色 mod，卡片挂着黄字、导入还被拦一下，体验完全不对；
    * 否则按目录名匹配，返回 ``match_character_detail`` 的结果。
    """
    explicit = str(meta.get("group") or meta.get("character") or "").strip()
    if explicit:
        return {"character": explicit, "confidence": "high", "candidates": [explicit],
                "guess": explicit}
    if kind == "assist":
        return {"character": "", "confidence": "high", "candidates": [], "guess": ""}
    return match_character_detail(" ".join(rel_parts).lower())


# 库里的**依赖包**（"重要前置"那类）按名字认：`（重要前置）RabbitFX v24_3d366`、
# `RabbitFX -ENDMI-`、`_deps\RabbitFX` ……
DEPENDENCY_NAME_HINTS = (
    "dependency", "deps", "_deps", "library mod", "rabbitfx", "orfix", "slotfix",
)


def is_dependency_package(name: str, path: Path | None = None) -> bool:
    """「名字像某个依赖」**且**「自己不带换装资源」= 真正的依赖包。

    ⚠️ **为什么不能只看名字**（2026-10-02 反馈定案）：作者的**皮肤包**常把前置名写进
    包名 —— `laevatain_as_2b_nier_-_by_primostudios_-_premium_nsfw_version_-_rabbitfx_da62a`
    是莱万汀的 2B 皮肤，只因名字带 `rabbitfx` 就被判成依赖，而：
      * 前端 `renderMods()` 对依赖项整条 `continue` ⇒ **卡片根本不渲染**；
      * `resolve_active_set()` 也把它排除出候选 ⇒ **永远进不了 staging**；
    用户看到的现象就是"**导入没反应 / 这个模型无法导入**"（实测连导三次，日志三次都写"完成"）。
    **判据**：真正的依赖包只有 .ini/.txt/.fx（`（重要前置）RabbitFX v24_3d366` 实测如此），
    皮肤包一定有 Meshes/Textures 或 .dds/.buf 之类的换装资源 —— 用这个把两者分开。
    `path is None` 时退化成"只看名字"（保持老行为，调用方拿不到路径的场合）。
    """
    lowered = str(name or "").lower()
    if not any(k in lowered for k in DEPENDENCY_NAME_HINTS):
        return False
    if path is None:
        return True
    try:
        return not has_mod_resources(Path(path))
    except OSError:
        return True


def infer_kind_and_group(
    rel_parts: Sequence[str],
    meta: dict[str, Any],
    path: Path | None = None,
) -> tuple[str, str]:
    """Return (kind, group) using metadata first, then folder-name aliases.

    ``kind`` 取值：``character``（换装/皮肤，要角色归属与同角色互斥）、
    ``dependency``（库依赖）、``tool``、以及 2026-10-01 新增的 **``assist``（辅助 mod）**。

    **辅助 mod**（用户 2026-10-01 要求：「能不能在 mod 管理器中增加一个辅助 mod 页，
    给这种非皮肤小 mod 留加载通道」）指的是"不换装、只改行为"的小 Mod ——
    例如「隐藏 UI＆UID」（`alt 1`）那种：没有 Meshes/Textures 资源，ini 全是
    `[TextureOverride_*] + handling = skip`（跳过某段绘制）。它们**不该**被当成角色 Mod
    （不然会被要求"确认角色归属"、还会按目录名分组），所以在这里单独判出来。
    """
    kind = str(meta.get("kind") or "").strip().lower()
    explicit_group = str(meta.get("group") or meta.get("character") or "").strip()
    matched = explicit_group or match_character(" ".join(rel_parts).lower())
    group = matched
    if not group:
        group = rel_parts[0] if rel_parts else "未分类"
    if not kind:
        lowered = " ".join(rel_parts).lower() + " " + str(meta.get("name", "")).lower()
        if is_dependency_package(lowered, path):
            kind = "dependency"
        elif any(k in lowered for k in ("tool", "tools", "utility")):
            kind = "tool"
        # ⚠️ 「加载页 / 壁纸」要排在 looks_like_assist **之前**判断：
        # 后者看的是"有没有换装资源"，而壁纸包整个都是 .dds 贴图 ⇒ 会被误判成皮肤。
        # 这类 Mod 不属于任何角色，**共用一个 group** ⇒ 同组互斥 = 同时只能开一个
        #（用户 2026-10-03：「这个算辅助性 mod，而且不能同时开多个」）。
        elif looks_like_wallpaper(path, rel_parts):
            kind = "assist"
            group = WALLPAPER_GROUP
        elif path is not None and looks_like_assist(path, rel_parts, meta, matched):
            kind = "assist"
            # 页内再细分组（用户要求）
            if group in ("", "未分类") or not matched:
                group = assist_group_of(rel_parts, meta)
        else:
            kind = "character"
    else:
        # ⚠️ `kind` 是用户显式指定过的（`mod.meta.json` 里有值）⇒ 上面的自动判据整块跳过。
        # 但**分组仍要算**：否则用户一旦手动移过"辅助 Mod"，它的 group 就永远停在目录名上，
        # 页面里的子类分组（加载页/壁纸、界面功能类…）全部失效。
        #（2026-10-03 实测：壁纸包被手动设过 kind 后，`looks_like_wallpaper` 明明返回 True，
        #  group 却还是 `female_images_dark_mode_a12a6` —— 就是这里漏了。）
        if kind == "assist" and (not group or group == rel_parts[0] if rel_parts else not group):
            group = assist_group_of(rel_parts, meta)
    return kind, group or "未分类"


# 辅助 mod 的判据（2026-10-01）：关键词只是"候选"，真正定案还要看**有没有换装资源**——
# 皮肤 mod 一定带 Meshes/Textures（或 .dds/.buf/mesh 之类），辅助 mod 不带。
ASSIST_HINTS = (
    "辅助", "隐藏", "去ui", "去界面", "水印", "工具", "菜单", "面板",
    "hide", "hud", "uid", "watermark", "overlay", "assist", "helper",
    "uifix", "nohud", "no-ui", "tool",
)
ASSIST_RESOURCE_DIRS = ("meshes", "textures", "texture", "mesh", "materials", "res")
ASSIST_RESOURCE_EXTS = {".buf", ".dds", ".mesh", ".ib", ".vb", ".fmt", ".obj", ".fbx"}
ASSIST_SKIP_RE = re.compile(r"^\s*handling\s*=\s*skip\b", re.IGNORECASE)

# ── 「加载页 / 壁纸」类（2026-10-03 用户要求）─────────────────────────────────
# 用户原话：「现在库里那个就是加载壁纸 mod，你看看结构，**这个算辅助性 mod，而且不能同时开多个**」。
#
# 它为什么会被判成 character：`looks_like_assist()` 的判据是"**有没有换装资源**"，
# 而换装资源的扩展名里含 `.dds` —— 壁纸包**整个就是一堆 .dds 贴图**
# （`Loadingscreens/ Startscreens/ DarkMode/ OperatorCVWall/ ProfileThemes/ …`），
# 于是被判成"有资源 ⇒ 皮肤 mod ⇒ 要角色归属"。可它根本不换任何角色的衣服。
#
# 判据：**目录名里出现已知的"界面/背景"类目录名，且不含角色换装目录**（Meshes/Textures）。
# 这一类**共用一个 group**，于是「同角色互斥」天然把它们变成"同时只能开一个"。
WALLPAPER_DIR_HINTS = (
    "loadingscreen", "loading_screen", "loadingscreens",
    "startscreen", "startscreens", "darkmode", "dark_mode",
    "wallpaper", "background", "backgrounds", "title", "titlescreen",
    "operatorcvwall", "operatoroverview", "profiletheme", "profilethemes",
    "monthlypass", "monthlypassbackground", "combo", "ef02slideprojector",
    # ⚠️ 2026-10-03 用户实测补入：「新下的壁纸没自动识别上」——
    # 那个包叫 **CharacterChange 1.3.1**（GameBanana），每个角色一份 ini，
    # 段名是 `[TextureOverride-<角色>BGProfile/-UI/-Battle/-Result/-Exhibit]`，
    # 改的是**角色界面背景 / UI / 战斗结算 / 展示图** ⇒ 属于加载页与壁纸类。
    # 目录名 `characterchange_131` 原先不在词表里，于是被漏判成换装。
    "characterchange", "character_change", "charchange",
)
# 出现这些说明它确实是"角色换装"，那就不能算壁纸类
WALLPAPER_NEGATIVE_HINTS = ("meshes", "textures", "texture", "materials")

WALLPAPER_GROUP = "加载页与壁纸"

# 辅助 Mod 的**子类**（用户 2026-10-03：「辅助 Mod 是标签，实际页面卡片中需要在卡片细分
# 加载页和功能类之类的」）—— 「辅助 Mod」只是标签页，页内卡片还要按子类分组显示。
ASSIST_GROUP_HIDE = "界面功能类"
ASSIST_GROUP_TOOL = "工具画质类"
ASSIST_GROUP_OTHER = "其它辅助"
# 命中这些词判成"界面/功能类"（隐藏 UI、去水印、改 HUD 这类）
ASSIST_FUNC_HINTS = (
    "隐藏", "去ui", "去界面", "水印", "hud", "uid", "hide", "watermark",
    "overlay", "nohud", "no-ui", "uifix", "界面", "菜单",
)


def assist_group_of(rel_parts: Sequence[str], meta: dict[str, Any]) -> str:
    """辅助 Mod 的**子类**（用于页内分组）。

    顺序有意义：**加载页/壁纸**优先（壁纸包也常含 ui 字样，但它是背景资源而不是改界面行为）。
    """
    lowered = "/".join(str(x) for x in rel_parts).lower() + " " + str(meta.get("name", "")).lower()
    if any(hint in lowered for hint in WALLPAPER_DIR_HINTS):
        return WALLPAPER_GROUP
    if any(k in lowered for k in ASSIST_FUNC_HINTS):
        return ASSIST_GROUP_HIDE
    if any(k in lowered for k in ("tool", "tools", "utility", "工具", "画质", "reshade", "postfx")):
        return ASSIST_GROUP_TOOL
    return ASSIST_GROUP_OTHER


# ── 「自带 UI 的 Mod」判据（2026-10-03 用户要求）─────────────────────────────
# 用户原话：「**看看有没有什么判据能判断一个 mod 是不是有 ui，有 ui 就不锁键，
#            那个 mod 不加入 reshade 的界面里**」。
#
# 为什么需要：有些 Mod **自带一套游戏内菜单**（ini 自绘，不是外部程序），典型代表是
# Snaccubus 的「庄方宜 模块化菜单包」（`zhuangfangyimodularmenumod`）。这类 Mod：
#   * **自己处理输入** —— 用 `/` 打开、鼠标左右中键选择、方向键/手柄导航；
#   * 因此**绝不能锁它的键**（锁了它自己的操作入口就废了）；
#   * 它的 `actions` 里绝大多数是「菜单怎么操作」（导航/点击/翻页）而不是换装本身，
#     **塞进 ReShade 面板毫无意义**（那个包被提取出 63 条，还有大量重复）。
#
# **判据 = 出现菜单状态变量**（实测对照）：
#   * 庄方宜菜单包：`$in_menu` / `$select_page` / `$clicktype` / `$clickcontroller` /
#     `$holdselect` —— **命中 5 个**；
#   * 普通换装 Mod（陈千语）：**命中 0 个**（它只有 `key = vk_right/vk_down/vk_left`）。
# 另加两条辅助特征（有则加分）：绑定鼠标键（`VK_LBUTTON`/`VBUTTON`）、绑定手柄键。
UI_MENU_VARS = (
    "$in_menu", "$in_character_menu", "$select_page", "$selectmenu",
    "$clicktype", "$clickcontroller", "$holdselect", "$holdselectcontroller",
)
# 自带 UI 的 Mod 往往会绑鼠标/手柄 —— 普通换装 Mod 不会
UI_INPUT_HINTS = ("vk_lbutton", "vk_rbutton", "vk_mbutton", "xbutton1", "xbutton2",
                  "xinput", "xbox", "gamepad", "controller")


def looks_like_ui_mod(path: Path | None, rel_parts: Sequence[str] = (), meta: dict | None = None) -> bool:
    """这个 Mod 是不是**自带游戏内 UI（菜单）**。

    命中即：**不锁它的键**、**不把它的动作塞进 ReShade 面板**、卡片上提示"游戏内按 / 打开"。
    """
    if path is None:
        return False
    try:
        text = ""
        for ini in sorted(path.rglob("*.ini"))[:12]:
            try:
                text += ini.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if len(text) > 400_000:
                break
    except OSError:
        return False
    if not text:
        return False
    low = text.lower()
    hits = sum(1 for v in UI_MENU_VARS if v in low)
    if hits >= 2:
        return True
    # 菜单变量只命中 1 个时，看有没有鼠标/手柄绑定佐证
    aux = sum(1 for k in UI_INPUT_HINTS if k in low)
    return hits >= 1 and aux >= 1


def looks_like_wallpaper(path: Path | None, rel_parts: Sequence[str]) -> bool:
    """是不是「加载页 / 壁纸」类（整包只换界面背景、不换角色衣服）。

    判据 = 命中已知的界面类目录名，且**不含**角色换装目录（Meshes/Textures）。
    """
    lowered = "/".join(str(p) for p in rel_parts).lower()
    if not any(hint in lowered for hint in WALLPAPER_DIR_HINTS):
        return False
    if any(neg in lowered for neg in WALLPAPER_NEGATIVE_HINTS):
        return False
    return True


def has_mod_resources(path: Path) -> bool:
    """这个 Mod 目录里有没有"换装资源"（模型/贴图）—— 用来区分皮肤 Mod 与辅助 Mod。"""
    if not path.is_dir():
        return False
    try:
        if any((path / name).is_dir() for name in ASSIST_RESOURCE_DIRS):
            return True
        for item in path.rglob("*"):
            if item.is_file() and item.suffix.lower() in ASSIST_RESOURCE_EXTS:
                return True
    except OSError:
        return False
    return False


def looks_like_assist(
    path: Path,
    rel_parts: Sequence[str],
    meta: dict[str, Any],
    character: str = "",
) -> bool:
    """判断是不是「辅助 mod」（不换装、只改行为的小 Mod）。

    判据（**前两条都要满足**）：
      ① **没有换装资源**（无 Meshes/Textures 目录，也没有 .dds/.buf/mesh 等文件）；
      ② 「名字/元数据里有辅助类关键词」**或**「ini 是跳过绘制型」（`handling = skip`）。
    再加一条**否决项**：
      ③ **只要能识别出角色，就不是辅助 mod** —— 这是 2026-10-01 拿 37 个真实 Mod 回归
         才定下来的：`女管理员去面具`、`莱万汀去除背后圆环` 这类"去掉某个部件"的 Mod
         结构上与"隐藏 UI"**完全一样**（都只有一个 `handling = skip` 的 ini、都没有资源），
         但它们**属于那个角色的变体**，就该留在角色库里参与同角色互斥；而
         `Hide UI＆UID` 归不到任何角色 —— 这才是真正的"辅助"。
         想反过来（把去部件的小 Mod 也当辅助），在卡片「⋯」里手动标记即可。
    """
    if character:
        return False
    if has_mod_resources(path):
        return False
    lowered = " ".join(rel_parts).lower() + " " + str(meta.get("name", "")).lower()
    if any(hint in lowered for hint in ASSIST_HINTS):
        return True
    try:
        for ini in list(path.rglob("*.ini"))[:4]:
            text = ini.read_text(encoding="utf-8", errors="replace")
            if any(ASSIST_SKIP_RE.match(line) for line in text.splitlines()):
                return True
    except OSError:
        return False
    return False


def _is_group_layout(entry: Path) -> bool:
    if direct_ini(entry) or _direct_images(entry):
        return False
    children_with_ini = [child for child in entry.iterdir() if child.is_dir() and direct_ini(child)]
    return bool(children_with_ini)


def mod_fingerprint(path: Path, *, max_files: int = 400) -> str:
    """Mod 的「内容指纹」：文件相对路径 + 大小，小文本文件（ini/json/txt/cfg ≤1 MB）再算内容 hash。

    只用于**标注"可能是同一个 Mod 的重复副本"**（用户 2026-10-01 要求 B），
    **不用于任何自动删除** —— 所以刻意**不读大文件**：几百 MB 的贴图包也只是一堆 stat，
    扫库不会被拖慢。返回空串表示读不到（该 Mod 跳过重复判定）。
    """
    digest = hashlib.sha1()
    try:
        files = sorted((p for p in path.rglob("*") if p.is_file()),
                       key=lambda p: str(p).lower())[:max_files]
    except OSError:
        return ""
    for file in files:
        try:
            size = file.stat().st_size
            digest.update(str(file.relative_to(path)).lower().encode("utf-8", "replace"))
            digest.update(str(size).encode())
            if size <= 1_048_576 and file.suffix.lower() in {".ini", ".json", ".txt", ".cfg"}:
                digest.update(hashlib.sha1(file.read_bytes()).digest())
        except OSError:
            continue
    return digest.hexdigest()


def scan_library(library_root: Path, mods_root: Path) -> list[ModInfo]:
    """Scan a flat or grouped mod library.

    Supported layouts::

        library/<Mod>/
        library/<Character>/<Mod>/
        library/_deps/<Dependency>/

    A top-level directory is treated as a character group only when it contains
    no direct .ini/cover and has at least one immediate child with direct .ini.
    Otherwise it is treated as a single mod (wrapper folders are preserved).
    """
    library_root = library_root.resolve()
    mods_root = mods_root.resolve()
    mods: list[ModInfo] = []
    if not library_root.is_dir():
        return mods

    for entry in sorted(p for p in library_root.iterdir() if p.is_dir()):
        if entry.name.startswith("."):
            continue
        if entry.name.lower() == "_deps":
            for dep in sorted(p for p in entry.iterdir() if p.is_dir()):
                if not has_any_ini(dep):
                    continue
                meta = load_sidecar(dep)
                mods.append(_make_mod_info(dep, dep, "_deps", "dependency", meta, mods_root))
            continue
        if entry.name.lower() in {"_endfieldmodcontroller_managed", "endfieldmodcontrollermanaged"}:
            continue

        if _is_group_layout(entry):
            children = [child for child in sorted(p for p in entry.iterdir() if p.is_dir())
                        if has_any_ini(child)]
            # **穿透"只有一个子目录"的包裹层**（2026-10-01 用户要求 B）：很多包被**整包**拷进
            # 库时会多包一层（`<包名>/<真 Mod>/…`）。只有一个子目录时那不是"按角色分组"，而是
            # "多包了一层" —— 若仍按分组处理，同一个 Mod 会被扫成**两条**（真实案例：
            # `library\Hide UI＆UID\` 与 `library\【辅助】隐藏UI和UID_alt加1\Hide UI＆UID\`
            # 各算一个，界面上出现两个同名条目、还会同时进 staging）。这里把它当**一个 Mod**，
            # 名字取里层目录名（与"导入 zip"得到的结果一致）；**只改扫描视角，不动文件系统**。
            # 子目录 ≥2 个时仍按"分组布局"处理（那才是 `library/<角色>/<Mod>/`）。
            if len(children) == 1:
                children = [children[0]]     # 包裹层 → 当作"一个 Mod"，不再按分组展开
            for child in children:
                meta = load_sidecar(child)
                # 包裹层（只有一个子目录）时**不带外层包名**参与识别 —— 否则组名/角色会取到
                # 包名（实测：`【辅助】隐藏UI和UID_alt加1` 这种归档名会被当成 group）。
                parts = [child.name] if len(children) == 1 else [entry.name, child.name]
                kind, group = infer_kind_and_group(parts, meta, child)
                mods.append(_make_mod_info(child, child, group, kind, meta, mods_root,
                                           char_detail=infer_character_detail(parts, meta, kind)))
            continue

        if not has_any_ini(entry):
            continue
        meta = load_sidecar(entry)
        parts = [entry.name]
        kind, group = infer_kind_and_group(parts, meta, entry)
        mods.append(_make_mod_info(entry, entry, group, kind, meta, mods_root,
                                   char_detail=infer_character_detail(parts, meta, kind)))

    # **重复副本标注**（2026-10-01 用户要求 B）：内容指纹相同的 Mod 只**标注**、
    # 绝不自动删（真实案例：`Hide UI＆UID` 在库里被放了两份 → 界面上两个同名条目、
    # 还会同时进 staging）。标注由前端显示成"与「X」内容相同（重复副本）"。
    first_by_fingerprint: dict[str, ModInfo] = {}
    for mod in mods:
        fingerprint = mod_fingerprint(mod.path)
        if not fingerprint:
            continue
        seen = first_by_fingerprint.get(fingerprint)
        if seen is None:
            first_by_fingerprint[fingerprint] = mod
        else:
            mod.duplicate_of = seen.name
    return mods


def _make_mod_info(
    source_root: Path,
    mod_root: Path,
    group: str,
    kind: str,
    meta: dict[str, Any],
    mods_root: Path,
    char_detail: dict[str, Any] | None = None,
) -> ModInfo:
    name = str(meta.get("name") or source_root.name)
    mod_id = str(meta.get("id") or stable_id(str(source_root.resolve()), name))
    # **辅助 mod 不参与同角色互斥**（用户 2026-10-01）：它的 conflict_group 用自身路径，
    # 每个辅助 mod 独占一组 —— 于是"隐藏 UI"能和任意角色服装同时生效，多个辅助 mod
    # 也能一起开；否则它们会共用 group（例如都以目录名为组）而互相挤掉。
    if kind == "assist":
        conflict_group = f"assist:{source_root.resolve()}"
    else:
        conflict_group = str(meta.get("conflict_group") or meta.get("character") or group)
    requires = meta.get("requires") or meta.get("dependencies") or []
    if isinstance(requires, str):
        requires = [requires]
    # ⚠️ **自带 UI（游戏内菜单）的 Mod 不把动作送进 ReShade 面板**
    # （2026-10-03 用户：「有 ui 就…**那个 mod 不加入 reshade 的界面里**」）。
    # 这类 Mod 的 actions 绝大多数是"菜单怎么操作"（导航/点击/翻页），
    # 实测那个模块化菜单包被提取出 **63 条**、还有大量重复 —— 塞进面板毫无意义，
    # 而且面板发它的"键"还会和鼠标/手柄操作打架。它自己就有菜单，用户直接用它。
    if looks_like_ui_mod(mod_root, [group or "", str(meta.get("name", ""))], meta):
        actions = []
    else:
        actions = parse_mod_actions(mod_root, mods_root)
    cover = find_cover(source_root, mod_root, meta)
    meta_path = next(
        (base / n for base in (source_root, mod_root) for n in ("mod.meta.json", "mod_info.json", "mod.yaml", "mod.yml") if (base / n).is_file()),
        None,
    )
    detail = char_detail or {}
    return ModInfo(
        id=mod_id,
        name=name,
        path=mod_root.resolve(),
        group=group,
        kind=kind,
        conflict_group=conflict_group,
        char_confidence=str(
            detail.get("confidence") or ("high" if group and group != "未分类" else "none")
        ),
        char_candidates=[str(c) for c in (detail.get("candidates") or [])],
        char_guess=str(detail.get("guess") or ""),
        requires=[str(x) for x in requires],
        source=str(meta.get("source") or ""),
        source_id=str(meta.get("source_id") or ""),
        actions=actions,
        meta_path=meta_path,
        cover_path=cover.resolve() if cover else None,
        source_root=source_root.resolve(),
    )


def iter_ini_files(mod_dir: Path) -> Iterator[Path]:
    for path in sorted(mod_dir.rglob("*.ini")):
        if any(part.startswith(".") for part in path.relative_to(mod_dir).parts):
            continue
        if path.name.lower() in {"d3dx.ini", "d3dx_user.ini"}:
            continue
        yield path



def namespaced_section_reference(section: str, namespace: str) -> str:
    """Return the fully namespaced section reference for a run/CommandList value."""
    if "\\" in section:
        return section
    prefixes = ("CommandList", "BuiltInCommandList", "CustomShader", "ShaderOverride", "TextureOverride")
    lower = section.lower()
    for prefix in prefixes:
        if lower.startswith(prefix.lower()):
            suffix = section[len(prefix):]
            ns = namespace.strip("\\")
            if not ns:
                return section
            return f"{prefix}\\{ns}\\{suffix}"
    return section

def _enrich_action(action: Action, ini_lines: Sequence[str], var_names: Sequence[str],
                   *, needs_rabbitfx: bool = False) -> Action:
    """给一个动作补上统一面板要用的展示字段（推测含义 / 键位 / 证据）。

    中文推不出时**不回退成编造的中文**，而是给出变量名清洗后的英文短语 ——
    用户 2026-10-01 的原则是"那些滑块要真的有用，不要就做表面功夫"，标签同理：
    宁可显示 `head horns` 也不要猜一个错的中文。

    *needs_rabbitfx* = 这个 ini **正文里真的调用了 RabbitFX**
    （``run = CommandList\\RabbitFX\\SetTextures``）。那种包在 RabbitFX 不加载时，
    **部件切了也不会有画面** —— 面板上直接标出来（用户 2026-10-02 实测：
    「全裸那些还是切不了，而且似乎原生按键也切不了」就是这个原因，与面板无关）。
    """
    tokens: list[str] = []
    for name in var_names:
        for token in hotkey_hints.mesh_tokens("", name, limit=8, lines=ini_lines):
            if token not in tokens:
                tokens.append(token)
    primary = var_names[0] if var_names else None
    action.context_tokens = tokens
    action.hint = hotkey_hints.hint_for(primary, section=action.section, tokens=tokens)
    action.var_phrase = hotkey_hints.var_phrase(primary) if primary else ""
    action.key_label = hotkey_hints.key_labels(action.original_keys)
    if needs_rabbitfx and action.hint:
        action.hint = f"{action.hint}（需 RabbitFX）"
    return action


def internal_marker_vars(text: str) -> set[str]:
    """找出「内部标记」变量（**不该出现在面板上**的那些）。

    现场例子（莱万汀 as 2B 那个 Mod）：`$creditinfo` 在**每个** `[Key*]` 段里都跟着一句
    `$creditinfo = 0`，Mod 自己的注释写着
    ``; This acts as the "lock" for the UI notification`` —— 它是 Mod 内部的 UI 通知锁，
    不是给用户用的开关，摆在面板上只会让人困惑（用户 2026-10-02：「creditinfo 要过滤掉」）。

    判据（保守，尽量不误伤真开关）：
      * 变量在 `[Constants]` 里**没有** `persist`；
      * 在同一个文件里被**赋值 ≥3 次**，且**每次都是单值**（没有 `0, 1` 这种逗号列表）。

    实测校准（莱万汀 2B 那个 Mod）：`$creditinfo` 出现 15 次、值是 `{0,1}`（不是恒定单值，
    所以"值恒定"那条判据**不成立** —— 第一版就是这么漏掉它的）。真开关要么带 `persist`
    （`$backSkirt`、`$mode` 都是），要么在自己的段里写成逗号列表（`$coat = 0, 1, 2`）——
    两者都不会命中。
    """
    persisted: set[str] = set()
    listed: set[str] = set()          # 出现过"逗号列表"赋值的变量（真开关的写法）
    counts: dict[str, int] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((";", "//", "#")):
            continue
        lowered = stripped.lower()
        if lowered.startswith("global") and "persist" in lowered:
            match = re.search(r"(\$[^\s=]+)", stripped)
            if match:
                persisted.add(match.group(1).lstrip("$").lower())
        match = _VAR_ASSIGN_RE.match(line)
        if not match:
            continue
        short = match.group(1).rpartition("\\")[2].lstrip("$").lower()
        counts[short] = counts.get(short, 0) + 1
        if "," in match.group(2):
            listed.add(short)

    return {
        name for name, count in counts.items()
        if name not in persisted and name not in listed and count >= 3
    }


def parse_mod_actions(mod_dir: Path, mods_root: Path) -> list[Action]:
    """Extract user-facing actions from every .ini inside *mod_dir*."""
    actions: list[Action] = []
    if not mod_dir.is_dir():
        return actions
    mod_id = stable_id(str(mod_dir.resolve()), mod_dir.name)
    for ini_path in iter_ini_files(mod_dir):
        try:
            text = read_text(ini_path)
        except OSError:
            continue
        ini_lines = text.splitlines()
        # 「内部标记」变量的名单（例如每个 Key 段里都跟着的 `$creditinfo = 0`）——
        # 这类东西不是给用户用的开关，面板上不该出现（用户 2026-10-02：「creditinfo 要过滤掉」）
        internal_markers = internal_marker_vars(text)
        # 正文里**真的**调用了 RabbitFX？（注释里提到不算 —— `; Draw-local isolation from
        # optional RabbitFX bindings` 那种是"声明不依赖"）—— 那种包在 RabbitFX 不加载时
        # 部件切了也没有画面，面板上要如实标出来
        needs_rabbitfx = any(
            "rabbitfx" in line.lower() and not line.strip().startswith(";")
            for line in ini_lines
        )
        ini_rel = str(ini_path.relative_to(mod_dir)).replace("\\", "/")
        namespace = parse_namespace(text) or _namespace_from_ini_path(ini_path, mods_root)
        _, sections = split_ini(text)
        for sec in sections:
            key_lines = [line for line in sec.lines if _KEY_RE.match(line)]
            if not key_lines:
                continue

            run_matches = [_RUN_RE.match(line) for line in sec.lines]
            run_command = next((m.group(1).strip() for m in run_matches if m), None)
            type_match = next((m.group(1).strip().lower() for m in (_TYPE_RE.match(line) for line in sec.lines) if m), None)
            condition_match = next((m.group(1).strip() for m in (_CONDITION_RE.match(line) for line in sec.lines) if m), "")
            # `type = hold`（按住生效）不是开关，`post $x = ...` 是每帧复位的瞬时状态
            # （庄方宜那套 KatModular 就有 `KeyMouseClick` / `KeyAlt` / `KeyW`）。
            # 把它们收进"统一面板"会造出一堆按下去没意义的滑块 —— 一律跳过。
            if type_match == "hold":
                continue
            var_assignments: list[tuple[str, str, str, list[str]]] = []   # (绝对名, 命名空间, 短名, 值)
            for line in sec.lines:
                m = _VAR_ASSIGN_RE.match(line)
                if m:
                    raw_name = m.group(1)
                    raw_value = m.group(2).strip()
                    values = [v.strip() for v in raw_value.split(",") if v.strip()] if raw_value else []
                    if not values:
                        continue
                    # 变量可能是相对的 `$coat`，也可能是**带命名空间的绝对引用**
                    # `$\FangyiVar\open`（KatModular 那一套全是这种写法，
                    # 老正则不认反斜杠，整个 Mod 因此一个开关都解析不出来）。
                    if "\\" in raw_name:
                        ns_part, _, short = raw_name.rpartition("\\")
                        own_ns = "\\" + ns_part.strip("\\")
                    else:
                        own_ns = namespace
                        short = raw_name
                    var_assignments.append((absolute_var(own_ns, short), own_ns, short, values))

            original_keys = [line.split("=", 1)[1].strip() for line in key_lines]

            if var_assignments and len(var_assignments) > 1:
                option_values = [values for _, _, _, values in var_assignments]
                option_count = len(option_values[0])
                if option_count and all(len(values) == option_count for values in option_values):
                    names = [short for _, _, short, _ in var_assignments]
                    # 只有一个取值（例如庄方宜那两个 `ResetPanel1Pos` 段全是 `= 0`）时，
                    # 它的语义是"按一下复位"而不是开关 —— 面板上给按钮，不给滑块。
                    if option_count == 1:
                        group_kind = "command"
                    elif type_match == "cycle" or option_count > 1:
                        group_kind = "cycle"
                    else:
                        group_kind = "toggle"
                    actions.append(_enrich_action(Action(
                        id=stable_id(mod_id, ini_rel, sec.header, ",".join(names), run_command or ""),
                        mod_id=mod_id,
                        mod_name=mod_dir.name,
                        label=_group_action_label(sec.header, names, run_command),
                        kind=group_kind,
                        ini_rel=ini_rel,
                        section=sec.header,
                        namespace=namespace,
                        values=[_group_option_label(names, option_values, index) for index in range(option_count)],
                        run_command=run_command,
                        run_command_full=namespaced_section_reference(run_command, namespace) if run_command else None,
                        original_keys=original_keys,
                        condition=condition_match,
                        source=str(ini_path),
                        targets=[target for target, _, _, _ in var_assignments],
                        option_values=[list(values) for values in option_values],
                        send_index=True,
                    ), ini_lines, names))
                    continue

            if var_assignments and internal_markers:
                var_assignments = [
                    item for item in var_assignments
                    if (item[2] or "").lstrip("$").lower() not in internal_markers
                ]
            if var_assignments:
                for target, own_ns, var_name, values in var_assignments:
                    kind = "cycle" if (type_match == "cycle" or len(values) > 1) else "toggle"
                    if kind == "toggle":
                        if values == ["0"]:
                            values = ["0", "1"]
                        elif len(values) == 1 and values[0] != "0":
                            values = ["0", values[0]]
                    label = _humanize_action_label(sec.header, var_name, run_command)
                    actions.append(_enrich_action(Action(
                        id=stable_id(mod_id, ini_rel, sec.header, var_name, run_command or ""),
                        mod_id=mod_id,
                        mod_name=mod_dir.name,
                        label=label,
                        kind=kind,
                        ini_rel=ini_rel,
                        section=sec.header,
                        namespace=own_ns,
                        var_name=var_name,
                        values=values,
                        run_command=run_command,
                        run_command_full=namespaced_section_reference(run_command, namespace) if run_command else None,
                        original_keys=original_keys,
                        condition=condition_match,
                        source=str(ini_path),
                        target_absolute=target,
                        targets=[target],
                        option_values=[list(values)],
                        send_index=True,
                    ), ini_lines, [var_name]))
            elif run_command:
                actions.append(_enrich_action(Action(
                    id=stable_id(mod_id, ini_rel, sec.header, run_command),
                    mod_id=mod_id,
                    mod_name=mod_dir.name,
                    label=_humanize_action_label(sec.header, None, run_command),
                    kind="command",
                    ini_rel=ini_rel,
                    section=sec.header,
                    namespace=namespace,
                    run_command=run_command,
                    run_command_full=namespaced_section_reference(run_command, namespace),
                    original_keys=original_keys,
                    condition=condition_match,
                    source=str(ini_path),
                    send_index=True,
                ), ini_lines, [], needs_rabbitfx=needs_rabbitfx))

    # ── 「辅助开关」屏蔽（用户 2026-10-02 原话：「**mode 是就应该被屏蔽，他是给其他按钮辅助的**」）──
    # 一个变量若被 **≥2 个别的动作**写在 condition 里（例如 `($mode == 3)` 这种分组条件），
    # 它自己就不是给用户点的功能，而是"分组 / 前置开关"；面板在切档前**会自动把它设好**
    # （见 `condition_switches`），所以从面板清单里去掉，免得混在真功能里让人点。
    condition_refs: dict[str, int] = {}
    for action in actions:
        for ref_name, _ref_value in _CONDITION_EQ_RE.findall(action.condition or ""):
            key = ref_name.lower()
            condition_refs[key] = condition_refs.get(key, 0) + 1
    if condition_refs:
        actions = [
            action for action in actions
            if condition_refs.get((action.var_name or "").lstrip("$").lower(), 0) < 2
        ]

    actions.sort(key=lambda a: (a.mod_id, a.ini_rel, a.section, a.id))
    return actions


def _humanize_action_label(section: str, var_name: str | None, run_command: str | None) -> str:
    label = section
    for prefix in ("Key", "Toggle", "Switch", "CommandList"):
        if label.lower().startswith(prefix.lower()):
            label = label[len(prefix):]
            break
    label = re.sub(r"[_\-]+", " ", label).strip()
    if var_name:
        label += f" ({var_name})"
    elif run_command:
        label += f" ({run_command})"
    return label or section


def _common_prefix(strings: list[str]) -> str:
    if not strings:
        return ""
    prefix = strings[0]
    for value in strings[1:]:
        while prefix and not value.lower().startswith(prefix.lower()):
            prefix = prefix[:-1]
        if not prefix:
            break
    return prefix


def _group_option_label(names: list[str], values: list[list[str]], index: int) -> str:
    active = [name for name, option_values in zip(names, values) if option_values[index] not in {"0", ""}]
    # Drop base names that are only prefixes of a more specific active name,
    # e.g. "dress" -> "dress1" for the first dress option.
    specific = [
        name for name in active
        if not any(name != other and other.lower().startswith(name.lower()) for other in active)
    ]
    chosen = specific or active
    return ", ".join(chosen) if chosen else "默认"


def _group_action_label(section: str, names: list[str], run_command: str | None) -> str:
    base = _humanize_action_label(section, None, run_command)
    prefix = _common_prefix(names)
    if prefix and len(prefix) >= 2 and any(name.lower() != prefix.lower() for name in names):
        return f"{base} ({prefix})"
    return base


def normalized_var_name(text: str) -> str:
    """3DMigoto 的变量名规范化：**只把 ASCII 大写字母变小写**（其余字符原样）。

    **为什么必须有它**（2026-10-02 实测根因，一手证据）：EFMI 把变量名按小写登记 ——
    `d3dx_user.ini` 里写的是 `$\\mods\\mc_佩丽卡_佩丽卡-ol装_linyoude\\0.ini\\coat`，
    而我们的 staging 目录名是 `MC_佩丽卡_佩丽卡-OL装_linyoude`。直接拿目录名当命名空间
    写进 `controller.ini`（`$\\mods\\MC_...\\0.ini\\coat = 1`）会引用一个**不存在的变量**，
    那行赋值被 3DMigoto 静默丢弃 —— 现象就是：面板点了没反应、`mc_action_seen` 在涨
    （提交确实执行了）、但 Mod 的变量一直是 0。对照：同一段 `[CommandListMC_Commit]` 里
    `$mc_action_seen = $mc_action_seen + 1`（本命名空间、本来就小写）**生效**，
    11 个跨命名空间引用（大写）**全都没生效**。

    只处理 ASCII 是因为 3DMigoto 那边也是 C 的 `::tolower`：中文等多字节字符不受影响
    （`OL装 → ol装`，中文原样）。
    """
    return "".join(ch.lower() if "A" <= ch <= "Z" else ch for ch in text)


def absolute_var(namespace: str, var_name: str) -> str:
    """Build the 3DMigoto absolute variable reference（**名字按原样**）。

    ⚠️ **不要在这里做任何大小写规范化**（2026-10-02 更正过一次错误推断）：
      * ini 层的变量名**大小写敏感** —— Mod 里声明的是 `global persist $backSkirt = 0`，
        引用写成 `$backskirt` 会被 3DMigoto 当成**未声明变量**、那行被丢弃
        （`ini_lint` 直接报出来，对照 EFMI 官方模板 `$\\EFMIv1\\required_version` 也是**原样**）；
      * `d3dx_user.ini` 里之所以全是小写，是**持久化层**的规范化写法（3DMigoto 自己写的
        文件格式），**不能反推成"ini 里引用变量要写小写"** —— 我把这两层搞混过一次。
    """
    ns = namespace.strip("\\")
    return f"$\\{ns}\\{var_name}"


# ---------------------------------------------------------------------------
# Hotkey shielding
# ---------------------------------------------------------------------------

@dataclass
class PatchRecord:
    mod_id: str
    original_text: str
    patched_text: str
    rel_path: str


# 这些段里装的是**要塞进 shader 的汇编文本**（`Pattern` / `Pattern.Replace` /
# `InsertDeclarations`），不是 ini 的控制流。段内的 `if_nz` / `endif` 都是**汇编指令**，
# 绝不能按 ini 的 if/endif 去配对 —— 2026-10-02 现场：`CutoutMask.ini` 的
# `Pattern.Replace` 里每行是 `...\n` 形式的汇编（`if_nz` 开头、`endif\n` 结尾），
# 被 `sanitize_ini_control_flow()` 当成"不配对的 endif"整段删掉 ⇒ 插进游戏 shader 的
# 汇编 `if_nz` 不闭合 ⇒ NVIDIA 编译器（`nvgpucomp64`）当场崩。**这是本项目改坏了用户
# 的 Mod 内容**（库里 59 行 → staging 55 行，而同一份包在 XXMI2 里能正常跑）。
_ASM_TEXT_SECTION_SUFFIXES = (".pattern", ".pattern.replace", ".insertdeclarations")
# 汇编文本行的尾巴：要塞进 shader 的每一行都以**字面** `\n` 结尾（两个字符：反斜杠 + n）。
# 这是"这行是汇编、不是 ini 控制流"的第二道判据（第一道是所在段的段名后缀）。
_ASM_TEXT_LINE_SUFFIX = "\\n"


def sanitize_ini_control_flow(path: Path) -> int:
    """Remove unmatched ``else`` / ``elif`` / ``endif`` lines from a staged INI.

    A few Endfield mods contain a duplicated ``endif``.  3DMigoto then reports
    ``Statement "endif" missing "if"`` and may skip the remainder of that mod.
    This cleanup is intentionally conservative: it only drops control-flow
    keywords that have no matching ``if`` in the same file.  It is applied to
    the staged copy, never to the user's library download.

    ⚠️ **绝不碰 shader 汇编文本**（2026-10-02 修）：`*.Pattern` /
    `*.Pattern.Replace` / `*.InsertDeclarations` 段里的内容是要**插进 shader 的汇编**，
    那里的 `if_nz … endif` 与 ini 的控制流无关。双重保险：① 整段跳过；② 行尾是字面
    ``\\n`` 的行也跳过（汇编文本的每一行都以它结尾）。**踩过的坑**：这两道闸都没有时，
    旗袍的 `CutoutMask.ini` 被删掉 4 行 `endif` ⇒ 汇编不闭合 ⇒ 游戏启动几十秒后崩在
    着色器编译器（而同一个包在别的 XXMI 环境里完好可用）。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    stack: list[str] = []
    removed = 0
    in_asm_text = False
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if stripped.startswith("["):
            section = stripped.strip("[]").strip().lower()
            in_asm_text = section.endswith(_ASM_TEXT_SECTION_SUFFIXES)
            out.append(line)
            continue
        if in_asm_text or line.rstrip("\r\n").endswith("\\n"):
            out.append(line)          # shader 汇编文本，原样保留
            continue
        if not stripped or stripped.startswith((";", "//", "#")):
            out.append(line)
            continue
        if lowered.startswith("if ") or lowered.startswith("if(") or lowered == "if":
            stack.append(line)
            out.append(line)
            continue
        if lowered.startswith(("elif ", "elif(")) or lowered == "elif":
            if stack:
                out.append(line)
            else:
                removed += 1
            continue
        if lowered.startswith("else") and (lowered == "else" or lowered[4:5] in (" ", "	", ";")):
            if stack:
                out.append(line)
            else:
                removed += 1
            continue
        if lowered.startswith("endif"):
            if stack:
                stack.pop()
                out.append(line)
            else:
                removed += 1
            continue
        out.append(line)
    if removed:
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write("".join(out))
    return removed


def ini_asm_if_unbalanced(path: Path) -> dict[str, int] | None:
    """这个 ini 里**要塞进 shader 的汇编**是不是 `if_nz` 比 `endif` 多？

    这是 **0.9.2 之前那个 bug 的确切指纹**：旧版 `sanitize_ini_control_flow()` 会把
    `[ShaderRegex*.Pattern.Replace]` 里、行尾带字面 ``\\n`` 的 **shader 汇编文本**当成
    ini 控制流，把 `endif` 整行删掉（实测：`RabbitFX.ini` 删 62 行、`（重要前置）湿润效果修复\\Shader.ini`
    删 11 行、庄方宜两份 `CutoutMask.ini` 各删 4 行）。汇编不闭合 ⇒ 驱动着色器编译器当场崩
    （`nvgpucomp64`）、剔除遮罩失效导致模型干脆出不來。

    **为什么需要它**：那个 bug 只改写 **staging 副本**（`activation.py` 里对 `dest` 调用的），
    所以**库里的原件是好的**；但**已经生成过的 staging 会一直带着伤** —— 用户升级到新版后
    若不重新「一键启动」，游戏读到的仍是坏的，他会以为"新版没用"。有了这个判据，自检就能
    发现并**按库里的原件自动重新生成**。

    返回 ``{"if_nz": n, "endif": m, "missing": n - m}``；配平、或文件里没有汇编文本时返回 ``None``。
    只数 `if_nz`（这是该 bug 的指纹，宁可漏报也不误报），不看 ini 自己的 `if/endif` 控制流。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    asm_lines = [ln for ln in text.splitlines() if ln.rstrip().endswith(_ASM_TEXT_LINE_SUFFIX)]
    if not asm_lines:
        return None
    asm = "\n".join(asm_lines)
    n_if = len(re.findall(r"\bif_nz\b", asm))
    n_end = len(re.findall(r"\bendif\b", asm))
    if n_if > n_end:
        return {"if_nz": n_if, "endif": n_end, "missing": n_if - n_end}
    return None


def find_unbalanced_asm_inis(root: Path, *, limit: int = 40) -> list[dict[str, Any]]:
    """扫一棵目录树，列出所有"汇编里 `if_nz` 比 `endif` 多"的 ini（旧版 bug 的受害者）。

    只在**控制器自己的产物**（staging 的 `MC_*` 目录）或用户库上调用，用于自检与修复。
    """
    found: list[dict[str, Any]] = []
    if not root.is_dir():
        return found
    for ini in sorted(root.rglob("*.ini")):
        if len(found) >= limit:
            break
        detail = ini_asm_if_unbalanced(ini)
        if detail:
            found.append({"path": str(ini), "name": ini.name, **detail})
    return found


# ⚠️⚠️ **"锁键"要绑的那个键，必须是面板协议里永远不发的键**（2026-10-03 定案）
#
# 设计意图（用户原话）：「按之前的设计应该是想让这些快捷键都不被触发，
# **你只要绑同一个没人按的就行**」—— 把所有 Mod 的 `[Key*]` 统一改写到同一个
# "没人按的键"，从而**锁住 Mod 自带热键**（否则游戏里会误触发），
# 真正的操作改由控制器面板走内部通道发送。
#
# **原来的 bug**：那个键选成了 `VK_F24` —— 而 F24 恰好是**面板协议的提交键**
#（见 `reshade_addon/src/endfieldmodcontroller_addon.cpp`）：
#     数字位：`VK_F13 + n`  ⇒ **F13..F22**
#     提交键：`VK_F24`
# 于是面板一提交，**所有 Mod 都读到 F24、全部一起切档**。
# 用户实测现象：「按陈千语的时候壁纸也会跟着动」。
#
# **修法**：改绑 `VK_F23` —— 它是 F13..F24 里**唯一既不在数字位范围、也不是提交键**的键。
# ⚠️ 改动面板协议（增删数字位或换提交键）时**必须同步复核这里**。
LOCKED_MOD_HOTKEY = "VK_F23"


def hotkey_for_mod(mod_id: str) -> str:
    """Mod 被锁后统一绑定的键（所有 Mod 相同：它是"没人按的键"）。"""
    return LOCKED_MOD_HOTKEY


def patch_mod_hotkeys(
    mod_dir: Path,
    backup_root: Path | None = None,
    mod_id: str | None = None,
    key_allocator: "Callable[[str], str] | None" = None,
) -> list[PatchRecord]:
    """Rebind original mod hotkeys to a harmless unused key.

    Keeping the [Key...] sections valid avoids the 3DMigoto Missing Key=
    warnings, while binding them to VK_F24 prevents the original mod hotkeys
    from firing.  The controller writes the state variables directly.
    """
    mod_dir = mod_dir.resolve()
    mod_id = mod_id or stable_id(str(mod_dir), mod_dir.name)
    records: list[PatchRecord] = []
    # ⚠️ **统一绑 `LOCKED_MOD_HOTKEY`（F23）**：目的是"锁住 Mod 自带热键"，
    # 所有 Mod 绑**同一个**没人按的键即可（用户 2026-10-03 明确：
    # 「你只要绑同一个没人按的就行」）。
    # 原来的 bug 是那个键误选成 F24 = 面板协议的**提交键** ⇒ 一提交所有 Mod 齐动。
    # 键由调用方**按动作段顺序分配**（保证全局唯一，见 `assign_hotkeys`）；
    # 没传就退回按 mod_id 派生（单 Mod 单独打补丁的场景）。
    _assigned = key_allocator or (lambda _n: hotkey_for_mod(mod_id))
    for ini_path in iter_ini_files(mod_dir):
        original = read_text(ini_path)
        lines = original.splitlines()
        changed = False
        new_lines: list[str] = []
        _, sections = split_ini(original)
        key_line_indexes: set[int] = set()
        for sec in sections:
            for idx in range(sec.start_line, sec.end_line):
                if _KEY_RE.match(lines[idx]):
                    key_line_indexes.add(idx)
        for idx, line in enumerate(lines):
            if idx in key_line_indexes:
                stripped = line.strip()
                prefix = line[: len(line) - len(line.lstrip())]
                if "=" in stripped:
                    key_name = stripped.split("=", 1)[0].strip()
                    new_lines.append(
                        f"{prefix}{key_name} = no_modifiers {_assigned(key_name)}"
                    )
                    changed = True
                    continue
            new_lines.append(line)
        if not changed:
            continue
        patched = chr(10).join(new_lines)
        if original.endswith(chr(10)):
            patched += chr(10)
        records.append(PatchRecord(
            mod_id=mod_id,
            original_text=original,
            patched_text=patched,
            rel_path=str(ini_path.relative_to(mod_dir)).replace(chr(92), "/"),
        ))
        ini_path.write_bytes(patched.encode("utf-8"))
        if backup_root is not None:
            backup_file = backup_root / mod_id / str(ini_path.relative_to(mod_dir))
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            # **只在第一次写备份**：第二次运行时 original 已经是上一次 patch 过的
            # 内容，无条件覆盖会把"真正的原始热键配置"冲掉，之后再也回不去
            # （2026-10-01 修）。
            if not backup_file.exists():
                backup_file.write_bytes(original.encode("utf-8"))
    return records


def restore_mod_hotkeys(mod_dir: Path, records: Sequence[PatchRecord]) -> None:
    mod_dir = mod_dir.resolve()
    for record in records:
        target = mod_dir / Path(record.rel_path)
        target.write_bytes(record.original_text.encode("utf-8"))


# ---------------------------------------------------------------------------
# Controller mod generation
# ---------------------------------------------------------------------------

CONTROLLER_NAMESPACE = "mc_controller"
CONTROLLER_ACTION_VAR = "controller_action"
CONTROLLER_VALUE_VAR = "controller_value"

# 面板遥控：往 **Mod 自己的（staging 副本）ini** 里注入的命令列表段名前缀。
# 为什么注入到 Mod 那边而不是在 controller.ini 里改 Mod 变量 —— 见 `inject_panel_lists`。
PANEL_LIST_PREFIX = "MC_Panel"
_PANEL_BEGIN = "; ===== EndfieldModController 面板遥控（自动生成，重新生成控制器时会重写）====="
_PANEL_END = "; ===== 面板遥控结束 ====="


def panel_list_section(wire_id: int) -> str:
    return f"CommandList{PANEL_LIST_PREFIX}{wire_id}"


def _short_var_of(target: str, ini_namespace: str) -> str | None:
    """绝对变量引用 → **本 ini 命名空间里的短名**（`$\\mods\\mc_x\\0.ini\\coat` → `coat`）。

    命名空间与本 ini 不一致时返回 None（那种引用写短名会指到别的变量上）。
    """
    name = target.strip()
    if not name.startswith("$"):
        return None
    if not name.startswith("$\\"):
        return name[1:]
    body = name[2:]
    ns, _, short = body.rpartition("\\")
    if not short:
        return None
    if normalized_var_name(ns) != normalized_var_name(ini_namespace.strip("\\")):
        return None
    return short


# 条件里形如 `$mode == 3` 的依赖（莱万汀那套 Mod：每个部件只在对应模式下才有反应）
_CONDITION_EQ_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*==\s*([^)&|]+)")


def condition_switches(condition: str, switchable: dict[str, str]) -> list[tuple[str, str]]:
    """从 `condition` 里挑出**需要先设好的**开关（变量, 值）。

    现场（莱万汀 as 2B）：`backSkirt` 的 condition 是
    ``($object_detected == 1) && ($mode == 3)`` —— 当前 `mode=0` 时，面板把 `$backSkirt`
    改对了**游戏里也不会有反应**（那个段根本不参与），用户的手感就是"点了没用"。

    ⇒ 注入段里先把这类"模式开关"设成要求的档位（等同用户手按 ↓ 切好模式、再按 →）。
    只认**本身也是面板上一个可切换变量**的名字（`$mode` ✓；`$object_detected` / `$active1`
    这类 EFMI 内建或每帧复位的运行时状态 ✗ —— 绝不能去写）。
    *switchable* = `{变量名小写: 变量名原样}`（用原样名去写，免得大小写对不上声明）。
    """
    if not condition:
        return []
    found: list[tuple[str, str]] = []
    used: set[str] = set()
    for name, value in _CONDITION_EQ_RE.findall(condition):
        key = name.lower()
        if key in switchable and key not in used:
            used.add(key)
            found.append((switchable[key], value.strip()))
    return found


def inject_panel_lists(
    ini_path: Path,
    entries: Sequence[tuple[int, Sequence[tuple[str, Sequence[str]]], Sequence[tuple[str, str]]]],
) -> list[str]:
    """把「切到下一档」的命令列表追加到（**staging 副本**的）Mod ini 末尾。

    **为什么在这里做**（2026-10-02 实测定案）：
      * `[CommandList]` 里的变量赋值**只认本 ini 声明过的 `$name`**；
      * 带路径的跨命名空间引用（`$\\mods\\mc_xxx\\0.ini\\coat = 1`）会被**静默丢弃** ——
        现场证据：同一个段里本命名空间的 `$mc_action_seen = $mc_action_seen + 1` 生效，
        而 11 个 Mod 变量引用**全部无效**（面板点了没反应）；
      * 但**跨命名空间调用命令列表是支持的**（`run = CommandList\\<ns>\\<name>`，
        源码 `ParseRunExplicitCommandList` + `get_namespaced_section_name_lower`）。

    所以"改 Mod 变量"这件事**必须发生在 Mod 自己的命名空间里**：这里把段写进 Mod 的
    （staging）ini（变量用短名 `$coat`），controller.ini 那边只用 `run =` 呼叫它。

    只改 staging 副本，**库原件一个字节都不动**；每轮 staging 都会重新复制，所以不会累积。
    返回注入的段名（供 controller.ini 生成 `run =` 引用）。
    """
    if not entries:
        return []
    try:
        text = read_text(ini_path)
    except OSError:
        return []

    # 防御：同一份 ini 万一被注入过两次，先把上一段摘掉（否则变量/段名重复）
    if _PANEL_BEGIN in text:
        head, _, rest = text.partition(_PANEL_BEGIN)
        _, _, tail = rest.partition(_PANEL_END)
        text = head.rstrip("\n") + "\n" + (tail or "").lstrip("\n")

    body: list[str] = [_PANEL_BEGIN]
    names: list[str] = []
    for wire_id, pairs, presets in entries:
        section = panel_list_section(wire_id)
        names.append(section)
        body.append(f"[{section}]")
        # 先把"模式开关"设好（例如 `$mode = 3`）—— 否则那个部件的段根本不参与，
        # 改了变量游戏里也没反应（用户手感就是"点了没用"）。见 condition_switches。
        for preset_name, preset_value in presets:
            body.append(f"${preset_name} = {preset_value}")
        for short_name, values in pairs:
            body.extend(next_step_lines("$" + short_name, list(values)))
        body.append("")
    body.append(_PANEL_END)

    patched = text.rstrip("\n") + "\n\n" + "\n".join(body) + "\n"
    try:
        ini_path.write_text(patched, encoding="utf-8", newline="")
    except OSError:
        return []
    return names


def inject_panel_lists_for_actions(
    actions: Sequence["Action"], *, library_root: Path | None = None
) -> dict[str, str]:
    """给一组动作注入面板命令列表。

    返回 `{action.id: "CommandList\\<ns>\\MC_Panel<wire>"}`（**只含注入成功的**）——
    controller.ini 用它生成 `run = …`；没在里面的动作，面板点不动（会在日志里说明）。

    ⚠️ **命名空间要用动作自己带的那个**（`parse_mod_actions` 推出来的）：很多 Mod ini
    **没有 `namespace =` 行**，命名空间是从**文件路径**推的（`\\mods\\<目录>\\<文件>`）——
    重新解析 ini 会拿到空值、导致整批被跳过（2026-10-02 踩过）。

    ⚠️ 传了 `library_root` 时会**拒绝写库内文件**（用户的 Mod 库只读是硬红线）。
    """
    by_ini: dict[Path, list[Action]] = {}
    for action in actions:
        if not action.source or action.wire_id <= 0 or not action.targets:
            continue
        by_ini.setdefault(Path(action.source), []).append(action)

    refs: dict[str, str] = {}
    for ini_path, group in by_ini.items():
        if library_root is not None:
            conflict = fsutil.library_conflict(Path(library_root), ini_path)
            if conflict:
                continue                      # 绝不碰用户的 Mod 库
        namespace = (group[0].namespace or "").strip("\\")
        if not namespace:
            continue
        switchable = {(a.var_name or "").lstrip("$").lower(): (a.var_name or "").lstrip("$")
                      for a in actions if a.var_name}
        entries: list[tuple[int, Sequence[tuple[str, Sequence[str]]], Sequence[tuple[str, str]]]] = []
        for action in group:
            pairs: list[tuple[str, Sequence[str]]] = []
            for target, values in zip(action.targets, action.option_values):
                short = _short_var_of(target, namespace)
                if short and values:
                    pairs.append((short, list(values)))
            if pairs:
                # 条件里若要求"先切模式"（`$mode == N`），注入段里先设好它
                presets = [
                    (name, value) for name, value in condition_switches(action.condition, switchable)
                    if name.lower() != (action.var_name or "").lstrip("$").lower()
                ]
                entries.append((action.wire_id, pairs, presets))
        names = inject_panel_lists(ini_path, entries)
        for action in group:
            if panel_list_section(action.wire_id) in names:
                refs[action.id] = namespaced_section_reference(
                    panel_list_section(action.wire_id), namespace
                )
    return refs


def next_step_lines(target: str, values: Sequence[str], *, indent: str = "") -> list[str]:
    """让一个 Mod 变量**切到下一档**的 3DMigoto 语句（面板协议第二版的核心）。

    面板只发"哪个动作"，档位由这里算：读当前值 → 写列表里的下一个值（末尾回到第一个）。
    这样面板**不需要知道** Mod 现在在第几档，你在游戏里手按键改过的档位也不会和面板打架。

    * `values` 只有一个值时（复位/命令类动作，例如 `ResetPanel1Pos = 0`）就是"写回它"；
    * 语法只用 `if` / `else if` / `else` + `endif`（3DMigoto **不认 `elif`**）；
    * `else` 兜底：当前值不在列表里（用户手改过、或 Mod 换了版本）→ 回到第一个值。
    """
    if not values:
        return []
    if len(values) == 1:
        return [f"{indent}{target} = {values[0]}"]
    out: list[str] = []
    for index, value in enumerate(values):
        keyword = "if" if index == 0 else "else if"
        out.append(f"{indent}{keyword} {target} == {value}")
        out.append(f"{indent}    {target} = {values[(index + 1) % len(values)]}")
    out.append(f"{indent}else")
    out.append(f"{indent}    {target} = {values[0]}")
    out.append(f"{indent}endif")
    return out


def generate_controller_mod(
    mods: Sequence[ModInfo],
    controller_dir: Path,
    *,
    dry_run: bool = False,
    user_ini_path: Path | None = None,
    library_root: Path | None = None,
) -> dict[str, Any]:
    """Generate controller.ini and actions.json for the active mod set."""
    controller_dir.mkdir(parents=True, exist_ok=True)
    actions: list[Action] = []
    mod_descriptions: dict[str, str] = {}
    for mod in mods:
        mod_descriptions[mod.id] = guess_mod_description(mod.name, mod.path)
        if mod.is_dependency:
            continue
        # 角色/分组是面板分栏的依据（统一面板按"角色 → Mod → 部件"排布）
        for action in mod.actions:
            action.char_group = mod.group or "未分类"
        actions.extend(mod.actions)

    dedup: dict[str, Action] = {}
    for action in actions:
        dedup.setdefault(action.id, action)
    actions = list(dedup.values())
    for action in actions:
        action.description = mod_descriptions.get(action.mod_id, "角色外观替换/切换")
    for index, action in enumerate(actions, start=1):
        action.wire_id = index

    # 面板遥控：把「切到下一档」注入 **Mod 自己的（staging）ini**，这里只记下 `run =` 要用的引用
    # （本文件里直接改 Mod 变量会被静默丢弃 —— 见文件头那段说明）。
    panel_refs: dict[str, str] = (
        {} if dry_run else inject_panel_lists_for_actions(actions, library_root=library_root)
    )

    lines: list[str] = [
        "; Generated by EndfieldModController PoC. Do not edit by hand.",
        ";",
        "; 面板协议（2026-10-02 第三版）—— 面板在**游戏进程内**伪造 EFMI 的读键状态",
        "; （见 reshade_addon/src/vkey_inject.h），把 F13..F24 标成「按下」：",
        ";   * **不带任何修饰键**（用户原话：「不要用 alt 这种辅助键」）—— 下面每一行",
        ";     `key =` 都不写 ctrl / alt / shift，用户想手按时也不必按修饰键。",
        ";   * F13 以上的键**标准键盘上不存在**，游戏与别的 addon 都不会绑它们",
        ";     （F6/F7 那批真实键当年被 DLSS5 的 NR 开关与第一人称切换抢走，才整体挪到这儿）。",
        ";   * 动作号用十进制逐位发送（F13+n 表示数字 n，共 F13..F22），最后按 **F24 提交**。",
        ";   * 提交后**不是**在这里改 Mod 变量，而是用 `run =` 呼叫**注入在 Mod 自己 ini 里**的那段",
        ";     （`CommandList\\<Mod 命名空间>\\MC_Panel<动作号>`）。",
        ";     原因（2026-10-02 实测）：本文件里直接写 `$\\mods\\...\\coat = 1` 这种跨命名空间赋值",
        ";     **会被静默丢弃** —— 同一段里本命名空间的 `$mc_action_seen` 生效、11 个 Mod 变量引用",
        ";     全部无效；而跨命名空间**调用命令列表**是 3DMigoto 明确支持的（源码",
        ";     `ParseRunExplicitCommandList`）。所以「切下一档」的语句跑在 Mod 自己的命名空间里",
        ";     （短名 `$coat`），本文件只负责呼叫。",
        f"namespace = {CONTROLLER_NAMESPACE}",
        "",
        "[Constants]",
        "global $controller_action = 0",
        "global $controller_value = 0",
        "global $mc_input = 0",
        "global persist $mc_controller_loaded = 20261002",
        "global persist $mc_last_wire = 0",
        "global persist $mc_present_frames = 0",
        "global persist $mc_present_t = 0",
        "global persist $mc_action_seen = 0",
    ]
    for action in actions:
        lines.append(f"global persist $mc_state_{action.wire_id} = 0")
    lines.append("")
    for digit in range(10):
        lines.extend([
            f"[KeyMC_Digit{digit}]",
            f"key = VK_F{13 + digit}",
            f"run = CommandListMC_Digit{digit}",
        ])
    lines.extend([
        "[KeyMC_Commit]",
        "key = VK_F24",
        "run = CommandListMC_Commit",
        "",
    ])
    for digit in range(10):
        lines.extend([
            f"[CommandListMC_Digit{digit}]",
            "$mc_input = $mc_input * 10" + (f" + {digit}" if digit else ""),
        ])
    # 提交：动作号到齐 → **把该动作涉及的每个变量切到下一档**。
    # ⚠️ 用 `if` / `else if` / `else` + 各自的 `endif`：3DMigoto **不认 `elif`**
    #    （2026-10-01 现场铁证：`elif` 那行被丢弃，它下面的赋值变成"无条件执行"，
    #     于是"点哪一档都没反应"）。
    lines.extend([
        "[CommandListMC_Commit]",
        "$mc_last_wire = $mc_input",
        "$mc_input = 0",
        "if $mc_last_wire != 0",
        "    $mc_action_seen = $mc_action_seen + 1",
        "    $controller_action = $mc_last_wire",
    ])
    for action in actions:
        lines.append(f"    ; {action.label}")
        lines.append(f"    if $mc_last_wire == {action.wire_id}")
        ref = panel_refs.get(action.id)
        if ref:
            # 呼叫**注入在 Mod 自己 ini 里**的那段（跨命名空间调用命令列表是支持的；
            # 跨命名空间改变量不支持 —— 这就是为什么"切档"语句要写在 Mod 那边）
            lines.append(f"        run = {ref}")
        if action.run_command:
            lines.append(f"        run = {action.run_command_full or action.run_command}")
        lines.append("    endif")
    lines.extend([
        "    $controller_action = 0",
        "    $mc_last_wire = 0",
        "endif",
        "",
        "[Present]",
        "; 探针节流（2026-10-02，用户要求清掉常驻探针）：每 5 秒记一次 ——",
        "; 「计数在涨」这个判据不变（诊断端只记录它的值），每帧开销归零。",
        "if time > $mc_present_t",
        "    $mc_present_t = time + 5",
        "    $mc_present_frames = $mc_present_frames + 1",
        "endif",
        "",
    ])
    controller_ini = "\n".join(lines)
    # **生成即安检**（2026-10-02）：按 3DMigoto 的源码规则把刚生成的 controller.ini 体检一遍。
    # 以前协议写错（变量名大小写、未声明变量、非法键名…）只能等用户进游戏"点了没反应"
    # 才暴露 —— 那正是这一版踩的坑（跨命名空间引用写了大写 ⇒ 赋值被静默丢弃）。
    from . import ini_lint

    lint_problems = ini_lint.lint_text(controller_ini)
    actions_manifest = {
        "controller_namespace": CONTROLLER_NAMESPACE,
        "controller_action_var": CONTROLLER_ACTION_VAR,
        "controller_value_var": CONTROLLER_VALUE_VAR,
        "lint_problems": lint_problems,
        "actions": [a.to_dict() for a in actions],
    }

    if not dry_run:
        (controller_dir / "controller.ini").write_text(controller_ini, encoding="utf-8")
        # 体检结果也落盘一份：出问题时直接看这个文件，不用把 ini 读一遍
        (controller_dir / "controller.lint.txt").write_text(
            "\n".join(lint_problems) + "\n" if lint_problems else "OK（没有会被 3DMigoto 静默跳过的行）\n",
            encoding="utf-8",
            newline="\n",
        )
        (controller_dir / "actions.json").write_text(
            json.dumps(actions_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tsv_header = [
            "id", "label", "kind", "mod_name", "values", "description",
            "current", "namespace", "var_name", "section", "run_command", "original_keys",
            "wire_id", "send_index", "merged",
            # ↓ 2026-10-01 统一面板新增（**只追加、不动前 15 列**：ReShade addon 用
            #   `fields.size() > N` 判断，新旧两版都能读同一份 actions.tsv）
            "hint", "key_label", "char_group", "condition",
        ]
        tsv_lines = ["	".join(tsv_header)]
        for action in actions:
            values = ",".join(tsv_cell(v) for v in action.values)
            current = ""
            if user_ini_path is not None:
                raw_state = read_user_var(Path(user_ini_path), CONTROLLER_NAMESPACE, f"mc_state_{action.wire_id}")
                if raw_state is not None:
                    current = raw_state
                elif action.namespace and action.var_name:
                    raw_current = read_user_var(Path(user_ini_path), action.namespace, action.var_name)
                    if raw_current is not None:
                        if action.send_index:
                            try:
                                current = str(action.values.index(raw_current))
                            except ValueError:
                                current = "0" if action.values else ""
                        else:
                            current = raw_current
            row = [
                action.id,
                tsv_cell(action.label),
                tsv_cell(action.kind),
                tsv_cell(action.mod_name),
                values,
                tsv_cell(action.description),
                tsv_cell(current),
                tsv_cell(action.namespace),
                tsv_cell(action.var_name or ""),
                tsv_cell(action.section),
                tsv_cell(action.run_command or ""),
                ";".join(tsv_cell(key) for key in action.original_keys),
                str(action.wire_id),
                "1" if action.send_index else "0",
                "1" if len(action.targets) > 1 else "0",
                tsv_cell(action.hint or action.var_phrase),
                tsv_cell(action.key_label),
                tsv_cell(action.char_group),
                tsv_cell(action.condition or ""),
            ]
            tsv_lines.append("	".join(row))
        (controller_dir / "actions.tsv").write_text("\n".join(tsv_lines) + "\n", encoding="utf-8", newline="\n")
        if user_ini_path is not None:
            try:
                set_user_var(Path(user_ini_path), CONTROLLER_NAMESPACE, CONTROLLER_ACTION_VAR, "0")
                set_user_var(Path(user_ini_path), CONTROLLER_NAMESPACE, CONTROLLER_VALUE_VAR, "0")
            except OSError:
                pass


    return actions_manifest


# ---------------------------------------------------------------------------
# d3dx_user.ini action queue
# ---------------------------------------------------------------------------

def locate_d3dx_user_ini(efmi_root: Path) -> Path:
    return efmi_root / "d3dx_user.ini"


def _format_user_var(namespace: str, var_name: str, value: str) -> str:
    # 名字**按原样**写（d3dx_user.ini 的小写是 3DMigoto 自己写回时的规范化，不是书写要求）
    ns = namespace.strip("\\")
    return f"$\\{ns}\\{var_name} = {value}"


def _user_var_key(namespace: str, var_name: str) -> str:
    ns = namespace.strip(chr(92))
    return f"$\\{ns}\\{var_name}"

def set_user_var(
    user_ini_path: Path,
    namespace: str,
    var_name: str,
    value: str,
    *,
    dry_run: bool = False,
) -> str:
    """Set one variable in d3dx_user.ini, preserving unrelated lines."""
    user_ini_path = user_ini_path.resolve()
    if user_ini_path.exists():
        original = user_ini_path.read_text(encoding="utf-8", errors="replace")
        if not dry_run:
            backup = user_ini_path.with_suffix(user_ini_path.suffix + ".mc.bak")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
    else:
        original = "; Generated by EndfieldModController PoC\n[Constants]\n"

    lines = original.splitlines()
    target_key = _user_var_key(namespace, var_name)
    target_line = _format_user_var(namespace, var_name, value)
    replaced = False
    new_lines: list[str] = []
    in_constants = False
    for line in lines:
        stripped = line.strip()
        if _INI_SECTION_RE.match(line):
            in_constants = stripped.lower() == "[constants]"
            new_lines.append(line)
            continue
        if in_constants and stripped.startswith("$"):
            key = stripped.split("=", 1)[0].strip()
            if key.lower() == target_key.lower():
                indent = line[: len(line) - len(line.lstrip())]
                new_lines.append(indent + target_line)
                replaced = True
                continue
        new_lines.append(line)
    if not replaced:
        out: list[str] = []
        inserted = False
        for line in new_lines:
            out.append(line)
            if not inserted and line.strip().lower() == "[constants]":
                out.append(target_line)
                inserted = True
        if not inserted:
            out += ["", "[Constants]", target_line]
        new_lines = out

    patched = "\n".join(new_lines) + "\n"
    if not dry_run:
        user_ini_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=user_ini_path.name + ".", suffix=".tmp", dir=str(user_ini_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(patched)
            os.replace(tmp_name, user_ini_path)
        finally:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return patched


def write_action_queue(user_ini_path: Path, action_id: str, value: str = "1", *, dry_run: bool = False) -> None:
    set_user_var(user_ini_path, CONTROLLER_NAMESPACE, CONTROLLER_ACTION_VAR, str(action_id), dry_run=dry_run)
    set_user_var(user_ini_path, CONTROLLER_NAMESPACE, CONTROLLER_VALUE_VAR, str(value), dry_run=dry_run)


def set_user_var_full(user_ini_path: Path, full_key: str, value: str, *, dry_run: bool = False) -> str:
    """Set a d3dx_user.ini variable from a ``$
amespacear`` key."""
    key = full_key.strip()
    if key.startswith("$"):
        key = key[1:]
    key = key.strip(chr(92))
    if chr(92) in key:
        namespace, var_name = key.rsplit(chr(92), 1)
        namespace = chr(92) + namespace.strip(chr(92))
    else:
        namespace, var_name = "", key
    return set_user_var(user_ini_path, namespace, var_name, value, dry_run=dry_run)


def read_user_var(user_ini_path: Path, namespace: str, var_name: str) -> str | None:
    if not user_ini_path.exists():
        return None
    key = _user_var_key(namespace, var_name).lower()
    text = user_ini_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().lower() == key:
            return v.strip()
    return None


# ---------------------------------------------------------------------------
# Launch helpers
# ---------------------------------------------------------------------------

def build_xxmi_launch_command(
    xxmi_launcher: Path,
    game_exe: Path | None = None,
    *,
    update: bool = False,
    nogui: bool = True,
) -> list[str]:
    """Build an XXMI Launcher command that starts EFMI.

    ``nogui=True`` starts the game in the background without the XXMI window.
    ``nogui=False`` shows the normal XXMI Launcher window and lets XXMI start
    the game from there, which is the behaviour most users expect from XXMI.
    """
    cmd = [str(xxmi_launcher)]
    if update:
        cmd.append("--update")
    if nogui:
        cmd.append("--nogui")
    cmd += ["--xxmi", "EFMI"]
    if game_exe is not None:
        cmd.append(str(game_exe))
    return cmd


def build_reshade_launch_env(runtime_dir: Path) -> dict[str, str]:
    """Return environment overrides that keep ReShade outside the game dir."""
    env = os.environ.copy()
    reshade_dir = (runtime_dir / "reshade").resolve()
    env["RESHADE_BASE_PATH_OVERRIDE"] = str(reshade_dir)
    env["RESHADE_DISABLE_LOADING_CHECK"] = "1"
    return env


# ---------------------------------------------------------------------------
# Dependency stub
# ---------------------------------------------------------------------------

DEFAULT_DEPENDENCIES = {
    "rabbitfx": {"display": "RabbitFX", "kind": "dependency"},
    "orfix": {"display": "Orfix", "kind": "dependency"},
    "slotfix": {"display": "Slotfix", "kind": "dependency"},
}

# **已知会导致游戏崩溃的依赖 —— 库里可以留着，但绝不加载它**。
# ⚠️ **当前是空的**：唯一那条（`rabbitfx`）已由用户实测结案（2026-10-02）。
#
# **RabbitFX 的完整经过**（留作判据的历史，别再重复栽这个跟头）：
#   2026-10-02 上午认定"RabbitFX 一进 staging，游戏启动几十秒后必崩在 `nvgpucomp64`"
#   （用户原话「**包含 RabbitFX 要程序能自动不加载它**」），于是列进这张表、默认屏蔽，
#   判据仍会照常发现"某个 Mod 引用了 RabbitFX"，只是不把它放进 staging。
#   **当天下午查清：那个现场是我们自己的 bug 造的** —— `core.sanitize_ini_control_flow()`
#   把 `[ShaderRegex*.Pattern.Replace]` 里**要塞进游戏 shader 的汇编 `endif`** 当成 ini 控制流
#   删掉了（拿 git 里修复前的旧实现真跑 `RabbitFX.ini`：`endif` 67 → **5**，**删了 62 行**），
#   汇编不闭合 ⇒ 驱动着色器编译器当场崩。0.9.2（`3af26e6`）修掉该 bug 后，回测显示 staging
#   产物与库里的原件**逐字节一致**；用户实测「**是带着 RabbitFX 的，进去渲染啥的都没啥问题**」
#   ⇒ **罪名洗清、条目移除**（用户 2026-10-02：「RabbitFX 可以移出 todo 了」）。
#
# **留给将来**：真发现某个依赖有害时，往这里加 key（依赖名小写）+ 原因字符串，
# `plan_dependencies(skip_known_bad=True)` / `resolve_active_set(skip_known_bad_dependencies=True)`
# 那套闸门机制照旧可用（只是默认值现在是 `False` = 不屏蔽）。
KNOWN_BAD_DEPENDENCIES: dict[str, str] = {}


def dependency_key_of(name: str) -> str:
    """这个名字属于哪个已知依赖（`rabbitfx` / `orfix` / `slotfix`）？都不像就返回空串。

    **按"包含"匹配，不是相等**（2026-10-02 用户实测暴露的问题）：用户手动导入库的依赖包
    往往带前缀/后缀 —— `（重要前置）RabbitFX v24_3d366`、`RabbitFX -ENDMI-`、
    `（重要前置）RabbitFX+v24_3d366_2` —— 用相等匹配**永远命不中**，于是"按需激活"看着
    在跑、实际上一个依赖都进不了 staging。
    """
    lowered = str(name or "").lower()
    for key in DEFAULT_DEPENDENCIES:
        if key in lowered:
            return key
    return ""

# ini 内部的命令引用：CommandList\<列表名>\<命令名>（不是外部依赖）
_COMMANDLIST_REF = re.compile(r"commandlist\\[^\s\"']*", re.IGNORECASE)
# ini 的行注释（3DMigoto 用 `;` 起）。
# ⚠️ **必须剔掉**（2026-10-02 用户现场定案）：庄方宜旗袍的 ini 里有一句注释 ——
# 「Draw-local isolation from **optional RabbitFX** bindings」—— 它其实是在声明
# "**本 Mod 不依赖 RabbitFX**（并防止它串进来）"，但早期判据扫的是 ini **全文**，
# 于是把注释里的名字当成了引用 ⇒ 误把 RabbitFX 激活进 staging ⇒ 游戏启动几十秒后
# 崩在着色器编译器（`nvgpucomp64`）。结论：**判据只看"真的用到"的代码，不看注释里的提及。**
_COMMENT = re.compile(r";.*$", re.M)


def collect_required_dependency_names(mods: Sequence[ModInfo]) -> list[str]:
    required: set[str] = set()
    known = {key.lower(): info["display"] for key, info in DEFAULT_DEPENDENCIES.items()}
    for mod in mods:
        for req in mod.requires:
            required.add(known.get(req.lower(), req))
        texts: list[str] = []
        for ini_path in iter_ini_files(mod.path):
            try:
                texts.append(read_text(ini_path))
            except OSError:
                continue
        # ① 先剔**注释**：注释里"提到"某个依赖不等于"用到"它（旗袍那句 isolation 声明
        #    直接把 RabbitFX 误激活了，见 _COMMENT 的注释）。
        haystack = _COMMENT.sub("", "\n".join(texts))
        # ② 3DMigoto 的 `CommandList\<列表名>\<命令名>` 是 **ini 内部的命令引用**，不是外部依赖。
        #    不先剔掉它，像 `pre run = CommandList\SlotFix\SaveDefault` 这样的行会让
        #    "SlotFix" 被误判成缺失依赖（2026-09-27 实测的误报来源）。
        haystack = _COMMANDLIST_REF.sub(" ", haystack).lower()
        for dep_id in DEFAULT_DEPENDENCIES:
            if dep_id.lower() in haystack:
                required.add(known[dep_id.lower()])
    return sorted(required)


def check_dependencies(library_root: Path, mods: Sequence[ModInfo]) -> dict[str, Any]:
    """Return a simple dependency status report without performing network I/O."""
    deps_dir = library_root / "_deps"
    present = {p.name.lower(): str(p) for p in deps_dir.iterdir() if p.is_dir()} if deps_dir.is_dir() else {}
    required = collect_required_dependency_names(mods)
    return {
        "required": required,
        "present": present,
        "missing": [r for r in required if r.lower() not in present],
        "unknown": [r for r in required if r.lower() not in DEFAULT_DEPENDENCIES],
    }


# ---------------------------------------------------------------------------
# Convenience orchestration for the PoC
# ---------------------------------------------------------------------------

def prepare_runtime(
    library_root: Path,
    mods_root: Path,
    runtime_dir: Path,
    *,
    patch: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan, patch and generate controller files for the PoC.

    ``patch`` 默认 **False**：2026-10-01 起不再改写 Mod 自带热键（控制面板还没做好，
    见 ``activation.stage_and_prepare``）—— 只有显式传 True 才把键改成 ``VK_F24``。
    """
    mods = scan_library(library_root, mods_root)
    patch_records: list[PatchRecord] = []
    if patch:
        backup_root = runtime_dir / "backups" / "hotkey_patch"
        for mod in mods:
            if mod.is_dependency:
                continue
            patch_records.extend(patch_mod_hotkeys(mod.path, backup_root, mod.id))
    manifest = generate_controller_mod(mods, runtime_dir / "controller", dry_run=dry_run)
    dep_report = check_dependencies(library_root, mods)
    return {
        "mods": [m.to_dict() for m in mods],
        "patch_records": [asdict(r) for r in patch_records],
        "actions_manifest": manifest,
        "dependency_report": dep_report,
    }


if __name__ == "__main__":  # pragma: no cover - tiny manual smoke path
    import argparse
    parser = argparse.ArgumentParser(description="EndfieldModController PoC core")
    parser.add_argument("--library", default="library")
    parser.add_argument("--mods-root", default="runtime/EFMI/Mods")
    parser.add_argument("--runtime", default="runtime")
    parser.add_argument("--patch", action="store_true",
                        help="改写 Mod 自带热键为 VK_F24（默认不改，见 prepare_runtime）")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args()
    result = prepare_runtime(
        Path(ns.library),
        Path(ns.mods_root),
        Path(ns.runtime),
        patch=ns.patch,
        dry_run=ns.dry_run,
    )
    print(json.dumps({
        "mod_count": len(result["mods"]),
        "patch_count": len(result["patch_records"]),
        "action_count": len(result["actions_manifest"]["actions"]),
        "dependency_report": result["dependency_report"],
    }, ensure_ascii=False, indent=2))
