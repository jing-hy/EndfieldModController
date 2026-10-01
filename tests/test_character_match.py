"""角色名自动匹配测试。

对应需求原话：「你找一下现在终末地全角色名，新加的 mod 要能自动匹配角色名」。
角色表在 ``endfieldmodcontroller/characters.json``（抓自官网干员情报页，33 位干员）。
"""
from __future__ import annotations

import unittest

from endfieldmodcontroller import core


class CharacterMatchTests(unittest.TestCase):
    def test_table_loaded_from_json(self) -> None:
        """角色表应当从 characters.json 载入，而不是只有内置兜底那 17 条。"""
        entries = core.load_character_aliases()
        self.assertGreaterEqual(len(entries), 30)
        pairs = core.character_alias_pairs()
        self.assertGreaterEqual(len(pairs), 80)

    def test_official_codenames_from_website(self) -> None:
        """官网英文代号（Mod 作者最常用的命名）必须能匹配到对应中文名。"""
        cases = {
            "estella": "埃特拉",
            "laevatain": "莱万汀",
            "perlica": "佩丽卡",
            "typhoeus": "提弗洛斯",
            "typhoea": "提弗洛斯",
            "catcher": "卡契尔",
            "wulfgard": "狼卫",
            "arclight": "弧光",
            "akekuri": "秋栗",
            "pogranichnik": "骏卫",
            "camille": "卡缪",
            "snowshine": "昼雪",
            "xaihi": "赛希",
        }
        for codename, want in cases.items():
            with self.subTest(codename=codename):
                self.assertEqual(core.match_character(codename), want)

    def test_alias_variants(self) -> None:
        """常见译名变体要归到同一个角色（否则同角色互斥会失效）。"""
        cases = {
            "佩丽卡-逆兔": "佩丽卡",
            "佩利卡-逆兔": "佩丽卡",       # 乳摇表用的译名
            "塞希泳装": "赛希",            # 用户 Mod 库里的写法
            "塞西泳装": "赛希",            # 17173 编号图里的写法
            "艾维文娜泳装": "艾维文娜",
            "艾闻维娜泳装": "艾维文娜",
            "弭弗连衣裙": "弭弗",
            "弥弗连衣裙": "弭弗",
            "小羊换装": "艾尔黛拉",        # 社区简称（用户纠正：小羊是艾尔黛拉，不是昼雪）
            "18+女管理员": "管理员",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(core.match_character(text.lower()), want)

    def test_pinyin_and_separator_variants(self) -> None:
        """拼音写法（连写 / 下划线 / 连字符 / 空格）都要能识别到角色。

        用户 2026-10-01 要求：「**中文拼音也要自动识别**」——国内作者常用拼音命名目录，
        以前别名表里只有中文名 + 官网英文代号，这些写法一个都匹配不上，于是新拖进来的
        Mod 全被判成"角色不确定"。
        """
        cases = {
            "zhuangfangyi_swim": "庄方宜",
            "Zhuang_Fang-Yi v2": "庄方宜",
            "zhuang fang yi": "庄方宜",
            "chenqianyu": "陈千语",
            "Chen_Qianyu_v2": "陈千语",
            "yingshi_v2": "萤石",
            "luoxi_dress": "洛茜",
            "luoqian": "洛茜",          # 「茜」的另一种读音
            "kamiao": "卡缪",
            "kamou": "卡缪",            # pypinyin 的默认音（社区两种念法都有人用）
            "alieshi": "阿列什",         # 「什」在人名里念 shí，不是默认的 shén
            "laiwanting": "莱万汀",
            "zhou_xue": "昼雪",
            "ai-wei-wen-na": "艾维文娜",
            "antaer": "安塔尔",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(core.match_character(text.lower()), want)

    def test_pinyin_does_not_invent_characters(self) -> None:
        """别为了拼音把无关的名字也认成角色（误报会让"同角色互斥"乱掉）。"""
        for text in ("emily_fox_unrelated", "random_pack_zzz", "sample_mod"):
            with self.subTest(text=text):
                self.assertEqual(core.match_character(text.lower()), "")
                self.assertEqual(core.match_character_detail(text.lower())["confidence"], "none")

    def test_guess_character_by_longest_related_text(self) -> None:
        """**预识别**：说不清归属时按"和哪个角色相关字数最多"猜一个（用户 2026-10-01 要求）。

        用户原话：「还要对一些没法完全确定归属的 Mod 进行预识别，就是匹配与哪个角色相关
        字数最多，比如杰哥属于洁尔佩塔，但**预识别过的还是要显示那个黄字无法确认归属**」
        → 所以预识别只写进 `guess`，**不能**抬高 `confidence`。
        """
        detail = core.match_character_detail("庄方宜和伊冯的合集")
        self.assertEqual(detail["confidence"], "low")     # 仍要用户确认
        self.assertEqual(detail["character"], "")
        self.assertEqual(detail["guess"], "庄方宜")        # 3 字 > 2 字

        detail2 = core.match_character_detail("杰哥+庄方宜 服装包")
        self.assertEqual(detail2["confidence"], "low")
        self.assertEqual(detail2["guess"], "庄方宜")

        # 社区昵称「杰哥」是洁尔佩塔的别名（用户明确指认）
        self.assertEqual(core.match_character("杰哥泳装"), "洁尔佩塔")
        self.assertEqual(core.match_character("jiege_swimsuit"), "洁尔佩塔")

    def test_guess_is_empty_without_clues(self) -> None:
        """一点线索都没有时不许硬猜（宁可不预选，也不能乱指一个角色）。"""
        detail = core.match_character_detail("mystery_pack_zzz")
        self.assertEqual(detail["confidence"], "none")
        self.assertEqual(detail["guess"], "")
        self.assertEqual(detail["candidates"], [])

    def test_guess_matches_character_when_confident(self) -> None:
        """高置信时 guess 与判定一致（前端可以用同一套逻辑预选）。"""
        detail = core.match_character_detail("estella_fat")
        self.assertEqual(detail["confidence"], "high")
        self.assertEqual(detail["character"], "埃特拉")
        self.assertEqual(detail["guess"], "埃特拉")

    def test_leading_name_wins_over_parenthetical(self) -> None:
        """名称开头的角色名优先于括号说明文字里的其它角色名。

        真实用例：`萤石去紧身衣…（会和黎风、伊冯等角色有贴图错误）` 应当判成「萤石」，
        而不是被括号里的「伊冯」抢走。
        """
        text = "萤石去紧身衣+z键尾巴萤石去除紧身衣去尾巴（会和黎风、伊冯等角色有贴图错误）"
        self.assertEqual(core.match_character(text.lower()), "萤石")

    def test_no_character_returns_empty(self) -> None:
        self.assertEqual(core.match_character("completely_unrelated_mod"), "")

    def test_infer_kind_and_group_uses_table(self) -> None:
        """扫描时应当用这张表归类，而不是只按第一层目录名。"""
        self.assertEqual(core.infer_kind_and_group(["estella_fat"], {}), ("character", "埃特拉"))
        self.assertEqual(core.infer_kind_and_group(["laevatain_bikini"], {}), ("character", "莱万汀"))
        # 元数据显式给了 group 时优先用元数据
        self.assertEqual(
            core.infer_kind_and_group(["whatever"], {"group": "自定义角色"}),
            ("character", "自定义角色"),
        )
        # 依赖仍然按关键词识别
        self.assertEqual(core.infer_kind_and_group(["_deps", "RabbitFX"], {})[0], "dependency")


if __name__ == "__main__":
    unittest.main()
