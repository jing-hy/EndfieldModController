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

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator, Sequence

from . import hotkey_hints


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
    name = re.sub(r"[^\w\-. \u4e00-\u9fff]+", "_", name.strip())
    return name or uuid.uuid4().hex[:8]


def valid_state_index(raw_state: Any, values: Sequence[str]) -> str | None:
    """把 `d3dx_user.ini` 里读到的 `mc_state_N` 变成**合法的档位索引**，非法就返回 None。

    `mc_state_N` 是我们自己写的档位索引，而 `d3dx_user.ini` 会长期保留历史值 ——
    现场出现过 `mc_state_1 = 5`（那一项只有 `0,1` 两档），结果面板显示"第 5 档"。
    合法区间是 `0 .. len(values)-1`；`values` 为空时不做限制（比如纯命令项）。
    """
    if raw_state is None:
        return None
    candidate = str(raw_state).strip()
    if not candidate:
        return None
    if not values:
        return candidate
    if not candidate.lstrip("-").isdigit():
        return None
    index = int(candidate)
    if 0 <= index < len(values):
        return candidate
    return None


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
        if any(k in lowered for k in ("dependency", "deps", "_deps", "library mod", "rabbitfx", "orfix", "slotfix")):
            kind = "dependency"
        elif any(k in lowered for k in ("tool", "tools", "utility")):
            kind = "tool"
        elif path is not None and looks_like_assist(path, rel_parts, meta, matched):
            kind = "assist"
        else:
            kind = "character"
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

def _enrich_action(action: Action, ini_lines: Sequence[str], var_names: Sequence[str]) -> Action:
    """给一个动作补上统一面板要用的展示字段（推测含义 / 键位 / 证据）。

    中文推不出时**不回退成编造的中文**，而是给出变量名清洗后的英文短语 ——
    用户 2026-10-01 的原则是"那些滑块要真的有用，不要就做表面功夫"，标签同理：
    宁可显示 `head horns` 也不要猜一个错的中文。
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
    return action


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
                ), ini_lines, []))

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


def absolute_var(namespace: str, var_name: str) -> str:
    """Build the 3DMigoto absolute variable reference."""
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


def sanitize_ini_control_flow(path: Path) -> int:
    """Remove unmatched ``else`` / ``elif`` / ``endif`` lines from a staged INI.

    A few Endfield mods contain a duplicated ``endif``.  3DMigoto then reports
    ``Statement "endif" missing "if"`` and may skip the remainder of that mod.
    This cleanup is intentionally conservative: it only drops control-flow
    keywords that have no matching ``if`` in the same file.  It is applied to
    the staged copy, never to the user's library download.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    stack: list[str] = []
    removed = 0
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
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


def patch_mod_hotkeys(
    mod_dir: Path,
    backup_root: Path | None = None,
    mod_id: str | None = None,
) -> list[PatchRecord]:
    """Rebind original mod hotkeys to a harmless unused key.

    Keeping the [Key...] sections valid avoids the 3DMigoto Missing Key=
    warnings, while binding them to VK_F24 prevents the original mod hotkeys
    from firing.  The controller writes the state variables directly.
    """
    mod_dir = mod_dir.resolve()
    mod_id = mod_id or stable_id(str(mod_dir), mod_dir.name)
    records: list[PatchRecord] = []
    safe_key = "no_modifiers VK_F24"
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
                    new_lines.append(f"{prefix}{key_name} = {safe_key}")
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


def generate_controller_mod(
    mods: Sequence[ModInfo],
    controller_dir: Path,
    *,
    dry_run: bool = False,
    user_ini_path: Path | None = None,
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

    lines: list[str] = [
        "; Generated by EndfieldModController PoC. Do not edit by hand.",
        f"namespace = {CONTROLLER_NAMESPACE}",
        "",
        "[Constants]",
        "global $controller_action = 0",
        "global $controller_value = 0",
        "global $mc_input = 0",
        "global $mc_pending_action = 0",
        "global persist $mc_controller_loaded = 20260926",
        "global persist $mc_last_wire = 0",
        "global persist $mc_last_value = 0",
    ]
    for action in actions:
        lines.append(f"global persist $mc_state_{action.wire_id} = 0")
    # 探针变量（见下方 `[Present]` 末尾）：`-999` = 从来没被赋值过 ——
    # 如果游戏跑完一轮后 `d3dx_user.ini` 里这些值还是 -999，说明 `[Present]` 那段根本没执行。
    for action in actions:
        if action.targets:
            lines.append(f"global persist $mc_probe_v{action.wire_id} = -999")
    lines.extend([
        "",
        "; Synthetic key protocol: Ctrl+Alt+Shift+F13..F24",
        "; 2026-10-01：数字位从 F1..F10 挪到 **F13..F22**、暂存 F23、提交 F24 ——",
        "; 旧键位会撞别的 addon（F6 = DLSS5 的 NR 开关、F7 = 第一人称切换，它们不看修饰键），",
        "; 用户实测「按开关外套会切第一人称 / 按切换头发开关了 DLSS5」就是这么来的。",
        "; F13 以上的键标准键盘上不存在，插件与游戏都不会绑。",
    ])
    for digit in range(10):
        lines.extend([
            f"[KeyMC_Digit{digit}]",
            f"key = ctrl alt shift VK_F{13 + digit}",
            f"run = CommandListMC_Digit{digit}",
        ])
    lines.extend([
        "[KeyMC_Stage]",
        "key = ctrl alt shift VK_F23",
        "run = CommandListMC_Stage",
        "[KeyMC_Commit]",
        "key = ctrl alt shift VK_F24",
        "run = CommandListMC_Commit",
        "",
    ])
    for digit in range(10):
        lines.extend([
            f"[CommandListMC_Digit{digit}]",
            "$mc_input = $mc_input * 10" + (f" + {digit}" if digit else ""),
        ])
    lines.extend([
        "[CommandListMC_Stage]",
        "$mc_pending_action = $mc_input",
        "$mc_input = 0",
        "[CommandListMC_Commit]",
        "$mc_last_wire = $mc_pending_action",
        "$mc_last_value = $mc_input",
    ])
    for action in actions:
        lines.extend([
            f"if $mc_pending_action == {action.wire_id}",
            f"    $mc_state_{action.wire_id} = $mc_input",
            "endif",
        ])
    lines.extend([
        "$controller_action = $mc_pending_action",
        "$controller_value = $mc_input",
        "$mc_input = 0",
        "",
        "[Present]",
        "if $controller_action != 0",
    ])

    for action in actions:
        lines.append(f"    ; action {action.id} :: {action.label}")
        lines.append(f"    if $controller_action == {action.wire_id}")
        if action.targets and action.option_values:
            for index in range(len(action.values)):
                # ⚠️ **每个档位一个独立的 `if`，绝不用 `elif`**（2026-10-01 定案）：
                # 现场现象是「Mod 自己的按键能换装（它改的就是同一个变量），但从面板点
                # 就完全没反应，而 `$mc_state_N` 又确实被写了」—— 说明"设置 Mod 变量"
                # 这一段没执行。3DMigoto/EFMI 的 ini 条件语法是
                # `if` / `else if` / `else` / `endif`，**`elif` 是 Python 语法、不是它的关键字**
                # （本文件 1289 行那段"清理 Mod 里 elif"的逻辑也印证了这点）。
                # 嵌套 if 在任何解析器下都合法，所以这里不赌。
                lines.append(f"        if $controller_value == {index}")
                for target, values in zip(action.targets, action.option_values):
                    if index < len(values):
                        lines.append(f"            {target} = {values[index]}")
                lines.append("        endif")
        lines.append(f"        $mc_state_{action.wire_id} = $controller_value")
        if action.run_command:
            lines.append(f"        run = {action.run_command_full or action.run_command}")
        lines.append("        $controller_action = 0")
        lines.append("    endif")

    lines.append("endif")
    # ── 运行时探针（2026-10-01 加，专治"面板点了但 Mod 变量没变"这类问题）──────
    # 把每个动作的**目标变量的当前值读回来**，存进我们自己的命名空间（`[Constants]` 里
    # 声明成 persist）→ 游戏退出时 `d3dx_user.ini` 里就能看到
    # `$\mc_controller\mc_probe_v<wire_id> = ?`：
    #   * 值 = 面板刚设的那个值 → **我们确实写进了 Mod 的变量**（问题在别处）；
    #   * 值 = -999（从没被赋值）→ **这段根本没执行**（语法/加载问题）；
    #   * 值一直是 0 而 Mod 自己的按键能让外观变化 → **我们写的是"影子变量"**（命名空间不对）。
    # 三种情况一次进出游戏即可区分，比反复猜快得多。
    lines.append("")
    for action in actions:
        target = (action.targets or [None])[0]
        if target:
            lines.append(f"$mc_probe_v{action.wire_id} = {target}")
    lines.append("")
    controller_ini = "\n".join(lines)
    actions_manifest = {
        "controller_namespace": CONTROLLER_NAMESPACE,
        "controller_action_var": CONTROLLER_ACTION_VAR,
        "controller_value_var": CONTROLLER_VALUE_VAR,
        "actions": [a.to_dict() for a in actions],
    }

    if not dry_run:
        (controller_dir / "controller.ini").write_text(controller_ini, encoding="utf-8")
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
                # ⚠️ **必须校验范围**：`mc_state_N` 是我们自己写的**档位索引**，而
                # `d3dx_user.ini` 是持久化文件、会留着历史脏值 —— 现场就出现过
                # `mc_state_1 = 5`（那一项只有 `0,1` 两档），于是面板显示"第 5 档"。
                # 合法的索引必须落在 `0 .. len(values)-1`。
                if raw_state is not None:
                    validated = valid_state_index(raw_state, action.values)
                    if validated is not None:
                        current = validated
                elif action.namespace and action.var_name:
                    raw_current = read_user_var(Path(user_ini_path), action.namespace, action.var_name)
                    if raw_current is not None:
                        if action.send_index:
                            try:
                                current = str(action.values.index(raw_current))
                            except ValueError:
                                current = "0" if action.values else ""
                        else:
                            # 同样校验：不是合法档位就不当当前值用
                            current = raw_current if (not action.values
                                                     or raw_current in action.values) else ""
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

# ini 内部的命令引用：CommandList\<列表名>\<命令名>（不是外部依赖）
_COMMANDLIST_REF = re.compile(r"commandlist\\[^\s\"']*", re.IGNORECASE)


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
        haystack = "\n".join(texts)
        # 3DMigoto 的 `CommandList\<列表名>\<命令名>` 是 **ini 内部的命令引用**，不是外部依赖。
        # 不先剔掉它，像 `pre run = CommandList\SlotFix\SaveDefault` 这样的行会让
        # "SlotFix" 被误判成缺失依赖（2026-09-27 实测的误报来源）。
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
