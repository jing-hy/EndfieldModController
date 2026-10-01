"""把 Mod 的开关变量翻译成人能看懂的东西。

用户 2026-10-01 的需求原话：「要标明原快捷键，**要自动识别那个变量的名称，推测含义**，
可能存在的变量名称可以从 `D:\\zmdmod\\mod集合` 中找」——统一面板上不能只写
`KeySwap_1 / $ear`，得让用户一眼看出这是「耳羽」。

三件事在这里做：

1. :func:`hint_for` —— 推测一个开关变量「管的是什么」。优先级：
   ① 变量名命中词表（`ear` → 耳羽）；
   ② ini 里引用该变量的 `if` 块附近的 mesh / 资源名命中词表
      （佩丽卡那个 `$ear` 旁边就写着 `; [mesh:LOD0.614a8c60-45003-0.hair_ear_copy]`）；
   ③ section 名（`KeyToggleUI` → 控制菜单）；
   ④ **兜底 = 原样返回变量名**（宁可少说，绝不编造一个看着像真的的中文）。
2. :func:`mesh_tokens` —— 从 ini 文本里把「谁引用了这个变量」的证据捞出来。
3. :func:`key_label` —— 把 3DMigoto 的键写法（`vk_left`、`ctrl alt shift VK_F1`、
   `VK_OEM_COMMA`）变成面板上直接显示的 `←` / `Ctrl+Alt+Shift+F1` / `,`。

词表本体是 `hotkey_hints.json`（随包，用 `scripts\\gen_hotkey_hints.py` 从
`mod集合` 扫出来 + 人工补的中文），**不含任何本机绝对路径**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

HINTS_FILE = Path(__file__).with_name("hotkey_hints.json")

# 变量名 → 中文。这是**主词典**：只有确定无疑的语义才写进来。
DEFAULT_VAR_HINTS: dict[str, str] = {
    "ear": "耳羽",
    "ears": "耳羽",
    "hair": "头发",
    "hair_res": "头发",
    "coat": "外套",
    "jacket": "外套",
    "bra": "胸衣",
    "underwear": "内衣",
    "glass": "眼镜",
    "glasses": "眼镜",
    "horn": "角",
    "horns": "角",
    "horndec": "角饰",
    "tail": "尾巴",
    "toe": "脚趾",
    "toes": "脚趾",
    "pants": "裤子",
    "dress": "连衣裙",
    "skirt": "裙子",
    "backskirt": "后裙摆",
    "shoes": "鞋子",
    "socks": "袜子",
    "sockscolor": "袜子配色",
    "sleeves": "袖子",
    "leg": "腿部",
    "legs": "腿部",
    "arm": "手臂",
    "armor": "护甲",
    "backarmor": "背部护甲",
    "belt": "腰带",
    "ring": "圆环",
    "top": "上衣",
    "cloth": "布料",
    "clothes": "服装",
    "body": "身体",
    "bodysize": "体型",
    "color": "配色",
    "colour": "配色",
    "hide_ui": "隐藏界面",
    "hide_uid": "隐藏 UID",
    "hud": "隐藏界面",
    "nudity": "全裸",
    "nude": "全裸",
    "swim": "泳装",
    "swimsuit": "泳装",
    "menu": "控制菜单",
    "in_menu": "菜单状态",
    "help": "帮助提示",
    "mask": "面具",
    "face": "面部",
    "head": "头部",
    "sockscolor_2": "袜子配色",
}

# ini 里的 mesh / 资源名片段（也用于变量名分词）→ 中文。
# 用于「变量名看不出含义」的 Mod（洛茜那种 $part_<hash>），以及
# 庄方宜那类「变量名本身就是英文描述」的 Mod（$draw_component_0_zfy_head_horns）。
DEFAULT_TOKEN_HINTS: dict[str, str] = {
    "hair_ear": "耳羽",
    "earpack": "耳羽",
    "ear": "耳羽",
    "hair": "头发",
    "head": "头部",
    "glass": "眼镜",
    "bra": "胸衣",
    "coat": "外套",
    "cloth": "布料",
    "skin": "皮肤",
    "whi": "内衣",
    "tail": "尾巴",
    "horn": "角",
    "horns": "角",
    "leg": "腿部",
    "legs": "腿部",
    "arm": "手臂",
    "arms": "手臂",
    "hand": "手部",
    "shoe": "鞋子",
    "sock": "袜子",
    "skirt": "裙子",
    "dress": "连衣裙",
    "belt": "腰带",
    "mask": "面具",
    "face": "面部",
    "eye": "眼睛",
    "body": "身体",
    "pack": "背包",
    "top": "上衣",
    "chest": "胸部",
    "pelvis": "下体",
    "bottom": "下装",
    "leggings": "紧身裤",
    "panel": "护片",
    "panels": "护片",
    "collar": "领子",
    "choker": "颈饰",
    "ribbon": "缎带",
    "ribbons": "缎带",
    "pasties": "贴片",
    "pasty": "贴片",
    "gape": "张开",
    "spread": "张开",
    "nipple": "胸部贴片",
    "cover": "遮盖件",
    "covered": "遮盖款",
    "uncovered": "无遮盖款",
    "inside": "内侧",
    "outside": "外侧",
    "sleeve": "袖子",
    "sleeves": "袖子",
    "cape": "披风",
    "cuffs": "袖口",
    "choker_2": "颈饰",
    "armband": "臂环",
    "decorations": "装饰",
    "decoration": "装饰",
    "funnels": "喇叭饰",
    "gloves": "手套",
    "boots": "靴子",
    "hat": "帽子",
    "hood": "兜帽",
    "scarf": "围巾",
    "necklace": "项链",
    "earring": "耳饰",
    "strap": "绑带",
    "straps": "绑带",
    "lace": "花边",
    "frill": "褶边",
    "shorts": "短裤",
    "tights": "丝袜",
    "stockings": "长袜",
    "uiskin": "界面",
}

# section 名 → 中文（只认「语义前缀」，前缀以外的编号忽略）。
DEFAULT_SECTION_HINTS: dict[str, str] = {
    "keytoggleui": "控制菜单",
    "keyswap": "部件切换",
    "keypart": "部件切换",
    "keytoggle": "开关",
    "keyswitch": "切换",
    "keycommand": "触发动作",
    "keyhide": "隐藏",
}

_MESH_RE = re.compile(r";\s*\[mesh:\s*([^\]]+)\]")
_RESOURCE_RE = re.compile(r"\bResource[-_]([A-Za-z0-9_\-\.]+)")
_HASH_RE = re.compile(r"\b[0-9a-f]{6,}\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")


def _load_json(path: Path | None = None) -> dict[str, Any]:
    target = path or HINTS_FILE
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


_cache: dict[str, dict[str, str]] = {}


def hints(path: Path | None = None) -> dict[str, dict[str, str]]:
    """载入（并缓存）词表：内置默认值 + `hotkey_hints.json` 覆盖/补充。"""
    key = str(path or HINTS_FILE)
    cached = _cache.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    merged: dict[str, dict[str, str]] = {
        "vars": dict(DEFAULT_VAR_HINTS),
        "tokens": dict(DEFAULT_TOKEN_HINTS),
        "sections": dict(DEFAULT_SECTION_HINTS),
    }
    data = _load_json(path)
    for name in ("vars", "tokens", "sections"):
        extra = data.get(name)
        if isinstance(extra, dict):
            for raw_key, raw_value in extra.items():
                if isinstance(raw_value, str) and raw_value.strip():
                    merged[name][str(raw_key).strip().lower()] = raw_value.strip()
    _cache[key] = merged
    return merged


def _normalize_words(text: str) -> list[str]:
    """`LOD0.614a8c60-45003-0.hair_ear_copy` → ['hair', 'ear', 'copy']。"""
    return _WORD_RE.findall(_HASH_RE.sub(" ", (text or "").lower()))


def mesh_tokens(
    ini_text: str,
    var_name: str,
    *,
    window: int = 4,
    limit: int = 24,
    lines: Sequence[str] | None = None,
) -> list[str]:
    """捞出「哪些网格/资源受这个变量控制」的证据串。

    只看变量出现行的**前后若干行**里的 `; [mesh:...]` 注释与 `Resource-*` 名字 ——
    这正是 Mod 作者自己写在 ini 里的语义（佩丽卡的 `$ear` 附近就有
    `hair_ear_copy` / `coat_earpack_copy`）。

    ``lines`` 允许调用方把已经切好的行缓存传进来，避免逐个变量重复 splitlines。
    """
    if not var_name:
        return []
    source = list(lines) if lines is not None else ini_text.splitlines()
    if not source:
        return []
    ref = re.compile(r"\$" + re.escape(var_name) + r"(?![A-Za-z0-9_])")
    found: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        text = re.sub(r"\s+", " ", raw).strip()
        if not text or text in seen:
            return
        seen.add(text)
        found.append(text)

    for index, line in enumerate(source):
        if not ref.search(line):
            continue
        for probe in range(max(0, index - window), min(len(source), index + window + 1)):
            for match in _MESH_RE.finditer(source[probe]):
                push(match.group(1))
            for match in _RESOURCE_RE.finditer(source[probe]):
                push(match.group(0))
        if len(found) >= limit:
            break
    return found[:limit]


def _token_candidates(token: str) -> list[str]:
    """把一个网格名拆成可匹配的候选片段，长的排前面（优先具体语义）。"""
    words = _normalize_words(token)
    candidates: list[str] = []
    for size in (3, 2, 1):
        for start in range(0, max(0, len(words) - size + 1)):
            candidates.append("_".join(words[start:start + size]))
    # 去重且保持"长片段优先"
    ordered: list[str] = []
    for item in candidates:
        if item and item not in ordered:
            ordered.append(item)
    ordered.sort(key=len, reverse=True)
    return ordered


# 变量名里的"结构词"：它们只说明这是第几个部件/哪种键，不含语义。
_VAR_NOISE = {
    "draw", "component", "components", "key", "keys", "swap", "swapkey", "part",
    "toggle", "toggles", "switch", "var", "vars", "state", "flag", "enable",
    "enabled", "on", "off", "default", "mod", "mods", "toggleui", "cmd", "main",
}
# 变量名分词后按"词"匹配（`$draw_component_0_zfy_head_horns` → head / horns）。
# 多个词命中时取**最靠左**的：Mod 作者命名习惯是从主要部件写起
# （`tail_hair` = 尾巴上的毛发 → 尾巴；`arms_sleeve_l` = 手臂袖子 → 手臂）。
def _is_noise_word(word: str) -> bool:
    """结构词（含 `swapkey12` 这种"结构词+编号"）不算含义。"""
    if word in _VAR_NOISE:
        return True
    match = re.fullmatch(r"([a-z]+)(\d+)", word)
    return bool(match) and match.group(1) in _VAR_NOISE


def _var_words(name: str) -> list[str]:
    return [w for w in _normalize_words(name) if len(w) > 1 and not w.isdigit() and not _is_noise_word(w)]


def var_phrase(name: str) -> str:
    """把变量名洗成一句能读的英文短语（去结构词与编号）：兜底显示用。"""
    words = _var_words(name)
    return " ".join(words)


def hint_for(
    var_name: str | None = None,
    *,
    section: str | None = None,
    tokens: Sequence[str] = (),
    table: dict[str, dict[str, str]] | None = None,
) -> str:
    """推测一个开关/切换变量的含义；推测不出来就返回空串（调用方据此回退到变量名）。"""
    tables = table or hints()
    var_table = tables.get("vars", {})
    token_table = tables.get("tokens", {})
    section_table = tables.get("sections", {})

    name = (var_name or "").strip().lower()
    if name:
        if name in var_table:
            return var_table[name]
        # 变量名去掉常见后缀再试一次（swapkey0 / part_82254888_001 / xxx_enable）
        stripped = re.sub(
            r"(_?(part|swap|swapkey|toggle|state|flag|enable|enabled|on|off|key|id|num|index|idx)|\d+)+$",
            "",
            name,
        ).strip("_")
        if stripped and stripped != name and stripped in var_table:
            return var_table[stripped]
        # 变量名自己就是描述：按词长度优先、同长度从左到右取第一个命中的词
        words = _var_words(name)
        for size in (3, 2, 1):
            for start in range(0, max(0, len(words) - size + 1)):
                candidate = "_".join(words[start:start + size])
                if candidate in token_table:
                    return token_table[candidate]

    for token in tokens:
        for candidate in _token_candidates(token):
            if candidate in token_table:
                return token_table[candidate]

    if section:
        key = re.sub(r"[^a-z0-9]", "", section.lower())
        for prefix, label in section_table.items():
            if key.startswith(prefix):
                return label
    return ""


# ---------------------------------------------------------------------------
# 键位美化
# ---------------------------------------------------------------------------

_SPECIAL_KEYS: dict[str, str] = {
    "vk_left": "←",
    "vk_right": "→",
    "vk_up": "↑",
    "vk_down": "↓",
    "vk_back": "Backspace",
    "vk_return": "Enter",
    "vk_escape": "Esc",
    "vk_space": "空格",
    "vk_tab": "Tab",
    "vk_oem_comma": ",",
    "vk_oem_period": ".",
    "vk_oem_1": ";",
    "vk_oem_2": "/",
    "vk_oem_3": "`",
    "vk_oem_4": "[",
    "vk_oem_5": "\\",
    "vk_oem_6": "]",
    "vk_oem_7": "'",
    "vk_oem_minus": "-",
    "vk_oem_plus": "=",
    "vk_lbutton": "鼠标左键",
    "vk_rbutton": "鼠标右键",
    "vk_mbutton": "鼠标中键",
    "vk_add": "小键盘+",
    "vk_subtract": "小键盘-",
    "vk_multiply": "小键盘*",
    "vk_divide": "小键盘/",
    "xb_guide": "手柄 Guide",
    "xb_left_thumb": "手柄左摇杆",
    "xb_right_thumb": "手柄右摇杆",
    "xb_dpad_up": "手柄十字上",
    "xb_dpad_down": "手柄十字下",
    "xb_dpad_left": "手柄十字左",
    "xb_dpad_right": "手柄十字右",
}

_MOD_LABEL = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
}


def _key_name(token: str) -> str:
    key = token.strip().lower()
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    match = re.fullmatch(r"vk_f(\d{1,2})", key)
    if match:
        return f"F{match.group(1)}"
    match = re.fullmatch(r"vk_numpad(\d)", key)
    if match:
        return f"小键盘{match.group(1)}"
    match = re.fullmatch(r"vk_(\d+)", key)
    if match:
        return f"VK{match.group(1)}"
    if key.startswith("vk_"):
        return key[3:].upper()
    if key.startswith("xb_"):
        return "手柄" + key[3:].replace("_", " ")
    if len(token.strip()) == 1:
        return token.strip().upper()
    # Mod 作者写的键名五花八门（`backspace` / `enter` / `R`），统一成首字母大写
    return token.strip().capitalize()


def key_label(spec: str) -> str:
    """3DMigoto 的 `key = ...` 写法 → 面板上能直接读的短标签。

    例：`vk_left` → `←`；`ctrl alt shift VK_F1` → `Ctrl+Alt+Shift+F1`；
    `no_modifiers VK_F24` → `F24`；`no_ctrl no_shift alt m` → `Alt+M`。
    """
    text = (spec or "").strip()
    if not text:
        return ""
    mods: list[str] = []
    plain: list[str] = []
    for token in text.replace("+", " ").split():
        low = token.strip().lower()
        if low.startswith("no_"):
            continue                      # no_ctrl / no_modifiers 只是"不允许"，不显示
        if low in _MOD_LABEL:
            label = _MOD_LABEL[low]
            if label not in mods:
                mods.append(label)
            continue
        plain.append(_key_name(token))
    parts = mods + plain
    if not parts:
        return ""
    return "+".join(parts)


def key_labels(specs: Iterable[str]) -> str:
    """多个键（`;` 分隔的 original_keys）合并成一个可读串，去掉重复。"""
    labels: list[str] = []
    for spec in specs:
        for piece in str(spec).split(";"):
            label = key_label(piece)
            if label and label not in labels:
                labels.append(label)
    return " / ".join(labels)
