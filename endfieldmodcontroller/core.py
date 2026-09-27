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
_VAR_ASSIGN_RE = re.compile(r"^\s*\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["values"] = list(self.values)
        d["original_keys"] = list(self.original_keys)
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
    try:
        payload = json.loads(CHARACTERS_JSON.read_text(encoding="utf-8"))
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
    """
    hits: dict[str, int] = {}
    for alias, canonical in character_alias_pairs():
        pos = haystack.find(alias)
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


def infer_character_detail(rel_parts: Sequence[str], meta: dict[str, Any]) -> dict[str, Any]:
    """角色归属 + 置信度，供界面在「不确定」时弹窗让用户选择。

    * ``meta`` 里显式写了 ``group`` / ``character``（用户此前确认过，或 Mod 自带）→ ``high``；
    * 否则按目录名匹配，返回 ``match_character_detail`` 的结果。
    """
    explicit = str(meta.get("group") or meta.get("character") or "").strip()
    if explicit:
        return {"character": explicit, "confidence": "high", "candidates": [explicit]}
    return match_character_detail(" ".join(rel_parts).lower())


def infer_kind_and_group(rel_parts: Sequence[str], meta: dict[str, Any]) -> tuple[str, str]:
    """Return (kind, group) using metadata first, then folder-name aliases."""
    kind = str(meta.get("kind") or "").strip().lower()
    group = str(meta.get("group") or meta.get("character") or "").strip()
    if not group:
        group = match_character(" ".join(rel_parts).lower())
    if not group:
        group = rel_parts[0] if rel_parts else "未分类"
    if not kind:
        lowered = " ".join(rel_parts).lower() + " " + str(meta.get("name", "")).lower()
        if any(k in lowered for k in ("dependency", "deps", "_deps", "library mod", "rabbitfx", "orfix", "slotfix")):
            kind = "dependency"
        elif any(k in lowered for k in ("tool", "tools", "utility")):
            kind = "tool"
        else:
            kind = "character"
    return kind, group or "未分类"


def _is_group_layout(entry: Path) -> bool:
    if direct_ini(entry) or _direct_images(entry):
        return False
    children_with_ini = [child for child in entry.iterdir() if child.is_dir() and direct_ini(child)]
    return bool(children_with_ini)


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
            for child in sorted(p for p in entry.iterdir() if p.is_dir()):
                if not has_any_ini(child):
                    continue
                meta = load_sidecar(child)
                parts = [entry.name, child.name]
                kind, group = infer_kind_and_group(parts, meta)
                mods.append(_make_mod_info(child, child, group, kind, meta, mods_root,
                                           char_detail=infer_character_detail(parts, meta)))
            continue

        if not has_any_ini(entry):
            continue
        meta = load_sidecar(entry)
        parts = [entry.name]
        kind, group = infer_kind_and_group(parts, meta)
        mods.append(_make_mod_info(entry, entry, group, kind, meta, mods_root,
                                   char_detail=infer_character_detail(parts, meta)))

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
            var_assignments: list[tuple[str, list[str]]] = []
            for line in sec.lines:
                m = _VAR_ASSIGN_RE.match(line)
                if m:
                    var_name = m.group(1)
                    raw_value = m.group(2).strip()
                    values = [v.strip() for v in raw_value.split(",") if v.strip()] if raw_value else []
                    if values:
                        var_assignments.append((var_name, values))

            original_keys = [line.split("=", 1)[1].strip() for line in key_lines]

            if var_assignments and len(var_assignments) > 1:
                option_values = [values for _, values in var_assignments]
                option_count = len(option_values[0])
                if option_count and all(len(values) == option_count for values in option_values):
                    names = [name for name, _ in var_assignments]
                    actions.append(Action(
                        id=stable_id(mod_id, ini_rel, sec.header, ",".join(names), run_command or ""),
                        mod_id=mod_id,
                        mod_name=mod_dir.name,
                        label=_group_action_label(sec.header, names, run_command),
                        kind="cycle" if (type_match == "cycle" or option_count > 1) else "toggle",
                        ini_rel=ini_rel,
                        section=sec.header,
                        namespace=namespace,
                        values=[_group_option_label(names, option_values, index) for index in range(option_count)],
                        run_command=run_command,
                        run_command_full=namespaced_section_reference(run_command, namespace) if run_command else None,
                        original_keys=original_keys,
                        condition=condition_match,
                        source=str(ini_path),
                        targets=[absolute_var(namespace, name) for name in names],
                        option_values=[list(values) for values in option_values],
                        send_index=True,
                    ))
                    continue

            if var_assignments:
                for var_name, values in var_assignments:
                    kind = "cycle" if (type_match == "cycle" or len(values) > 1) else "toggle"
                    if kind == "toggle":
                        if values == ["0"]:
                            values = ["0", "1"]
                        elif len(values) == 1 and values[0] != "0":
                            values = ["0", values[0]]
                    label = _humanize_action_label(sec.header, var_name, run_command)
                    actions.append(Action(
                        id=stable_id(mod_id, ini_rel, sec.header, var_name, run_command or ""),
                        mod_id=mod_id,
                        mod_name=mod_dir.name,
                        label=label,
                        kind=kind,
                        ini_rel=ini_rel,
                        section=sec.header,
                        namespace=namespace,
                        var_name=var_name,
                        values=values,
                        run_command=run_command,
                        run_command_full=namespaced_section_reference(run_command, namespace) if run_command else None,
                        original_keys=original_keys,
                        condition=condition_match,
                        source=str(ini_path),
                        target_absolute=absolute_var(namespace, var_name),
                        targets=[absolute_var(namespace, var_name)],
                        option_values=[list(values)],
                        send_index=True,
                    ))
            elif run_command:
                actions.append(Action(
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
                ))

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
    lines.extend([
        "",
        "; Synthetic key protocol: Ctrl+Alt+Shift+F1..F12",
    ])
    for digit in range(10):
        lines.extend([
            f"[KeyMC_Digit{digit}]",
            f"key = ctrl alt shift VK_F{digit + 1}",
            f"run = CommandListMC_Digit{digit}",
        ])
    lines.extend([
        "[KeyMC_Stage]",
        "key = ctrl alt shift VK_F11",
        "run = CommandListMC_Stage",
        "[KeyMC_Commit]",
        "key = ctrl alt shift VK_F12",
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
                branch = "if" if index == 0 else "elif"
                lines.append(f"        {branch} $controller_value == {index}")
                for target, values in zip(action.targets, action.option_values):
                    if index < len(values):
                        lines.append(f"            {target} = {values[index]}")
            lines.append("        endif")
        lines.append(f"        $mc_state_{action.wire_id} = $controller_value")
        if action.run_command:
            lines.append(f"        run = {action.run_command_full or action.run_command}")
        lines.append("        $controller_action = 0")
        lines.append("    endif")

    lines += ["endif", ""]
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
        haystack = "\n".join(texts).lower()
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
    patch: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan, patch and generate controller files for the PoC."""
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
    parser.add_argument("--no-patch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args()
    result = prepare_runtime(
        Path(ns.library),
        Path(ns.mods_root),
        Path(ns.runtime),
        patch=not ns.no_patch,
        dry_run=ns.dry_run,
    )
    print(json.dumps({
        "mod_count": len(result["mods"]),
        "patch_count": len(result["patch_records"]),
        "action_count": len(result["actions_manifest"]["actions"]),
        "dependency_report": result["dependency_report"],
    }, ensure_ascii=False, indent=2))
