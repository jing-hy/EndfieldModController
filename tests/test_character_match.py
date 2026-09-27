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
