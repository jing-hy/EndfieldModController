"""锁键（Mod 热键改写目标）**不能和面板协议键撞**。

2026-10-03 用户实测：「按陈千语的时候壁纸也会跟着动」。
根因：`patch_mod_hotkeys` 把所有 Mod 的 `[Key*]` 统一改写成 `no_modifiers VK_F24`
（意图是"锁住 Mod 自带热键"），但 **F24 恰好是面板协议的提交键** ——
`reshade_addon/src/endfieldmodcontroller_addon.cpp` 里：

    数字位：`VK_F13 + n`  ⇒ **F13..F22**
    提交键：`VK_F24`

于是面板一提交，所有 Mod 都读到 F24、**全部一起切档**。

用户对设计的说明（原话）：「按之前的设计应该是想让这些快捷键都不被触发，
**你只要绑同一个没人按的就行**」—— 所以修法不是"一个 Mod 一个键"，
而是"**统一绑一个面板永远不发的键**"= `VK_F23`。

这里钉住：**锁键与面板协议键集合无交集**。以后改面板协议（增删数字位/换提交键）时，
这个测试会立刻报出来。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from endfieldmodcontroller.core import LOCKED_MOD_HOTKEY, hotkey_for_mod

ROOT = Path(__file__).resolve().parents[1]
ADDON_CPP = ROOT / "reshade_addon" / "src" / "endfieldmodcontroller_addon.cpp"


def _panel_protocol_keys() -> set[str]:
    """从 addon 源码里读出面板协议实际使用的 VK 名（数字位 + 提交键）。

    解析两处：
    * `VK_F13 + (ch - '0')`  ⇒ 数字位 = F13..F13+9 = F13..F22
    * `g_pending_keys.push_back(VK_F24)` ⇒ 提交键
    解析不出来就跳过（不因为源码改写形态而误判）。
    """
    if not ADDON_CPP.is_file():
        return set()
    text = ADDON_CPP.read_text(encoding="utf-8", errors="replace")
    keys: set[str] = set()
    # 数字位起点
    m = re.search(r"VK_F(\d+)\s*\+\s*\(\s*ch\s*-\s*'0'\s*\)", text)
    if m:
        start = int(m.group(1))
        keys.update(f"VK_F{n}" for n in range(start, start + 10))
    # 显式 push_back 的键（提交键在这）
    for mm in re.finditer(r"push_back\(\s*VK_F(\d+)\s*\)", text):
        keys.add(f"VK_F{int(mm.group(1))}")
    return keys


class LockedHotkeyTests(unittest.TestCase):
    def test_locked_key_is_uniform(self) -> None:
        """所有 Mod 绑**同一个**键（用户明确的设计意图）。"""
        self.assertEqual({hotkey_for_mod(m) for m in ("陈千语", "壁纸", "洁尔佩塔", "")},
                         {LOCKED_MOD_HOTKEY},
                         "锁键应当对所有 Mod 一致 —— 它是'没人按的键'，不用于区分 Mod")

    def test_locked_key_never_collides_with_panel_protocol(self) -> None:
        """⭐ 核心回归：锁键不能是面板协议用到的任何键（否则一提交就全体切档）。"""
        protocol = _panel_protocol_keys()
        self.assertTrue(protocol, "没能从 addon 源码里解析出面板协议键（解析器该更新了）")
        self.assertNotIn(LOCKED_MOD_HOTKEY, protocol,
                         f"锁键 {LOCKED_MOD_HOTKEY} 与面板协议键 {sorted(protocol)} 撞了 —— "
                         f"会让所有 Mod 一起响应面板操作")

    def test_locked_key_is_an_unpressable_function_key(self) -> None:
        """锁键应当是键盘上**按不到**的 F13..F24 之一。"""
        m = re.fullmatch(r"VK_F(\d+)", LOCKED_MOD_HOTKEY)
        self.assertIsNotNone(m, f"锁键应当形如 VK_Fnn，实际是 {LOCKED_MOD_HOTKEY}")
        assert m is not None
        self.assertTrue(13 <= int(m.group(1)) <= 24,
                        "锁键应当在 F13..F24 里（标准键盘上没有这些键，游戏/IME 都不会占用）")


if __name__ == "__main__":
    unittest.main()
