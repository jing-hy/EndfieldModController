"""GameBanana 多文件页面：**必须按更新时间挑主包，并把配套小文件也带上**。

2026-10-03 用户实测：「uimod 好像没生效」。
查下来是我们下载挑错了文件：API 的 `_aFiles` **不是按时间排的**，
那个 Mod 的顺序是 1.3.1(86MB) / _core_2(275B) / _core_ffd68(292B) / 1.8.2(957MB)，
而旧实现 `next((entry for entry in files if not archived), files[0])` 取的是
**列表第一个** ⇒ 下到了 1.3.1 旧版；同时作者单独发的 `_Core.ini`
（`_core_2.zip`，275 B）**从来没被下载过** —— 主包缺它根本不工作。
"""
from __future__ import annotations

import unittest

from endfieldmodcontroller import moddl


def _f(name: str, size: int, added: int, aux: bool = False, archived: bool = False) -> dict:
    return {"file": name, "size": size, "url": f"https://example.invalid/{name}",
            "added": added, "aux": aux, "archived": archived, "version": ""}


class SplitModFilesTests(unittest.TestCase):
    def test_picks_newest_not_first(self) -> None:
        """⭐ 核心回归：不能取列表第一个，要取**更新时间最新**的。"""
        files = [
            _f("characterchange_131.zip", 86_833_333, 1_788_768_520),
            _f("_core_2.zip", 275, 1_788_779_065, aux=True),
            _f("_core_ffd68.zip", 292, 1_788_798_846, aux=True),
            _f("changescreens_182.zip", 957_109_937, 1_789_146_861),
        ]
        main, aux = moddl.split_mod_files(files)
        assert main is not None
        self.assertEqual(main["file"], "changescreens_182.zip",
                         "应当选更新时间最新的主包，而不是列表里的第一个")
        self.assertEqual({f["file"] for f in aux}, {"_core_2.zip", "_core_ffd68.zip"})

    def test_aux_not_chosen_as_main(self) -> None:
        """配套小文件不能被当成主包（哪怕它时间更新）。"""
        files = [
            _f("main_mod.zip", 50_000_000, 100),
            _f("_core_later.zip", 300, 999, aux=True),
        ]
        main, aux = moddl.split_mod_files(files)
        assert main is not None
        self.assertEqual(main["file"], "main_mod.zip")
        self.assertEqual([f["file"] for f in aux], ["_core_later.zip"])

    def test_archived_ignored_unless_only_option(self) -> None:
        files = [_f("old.zip", 10, 1, archived=True), _f("new.zip", 20, 2)]
        main, _aux = moddl.split_mod_files(files)
        assert main is not None
        self.assertEqual(main["file"], "new.zip")
        only_archived = [_f("only.zip", 10, 1, archived=True)]
        main2, _ = moddl.split_mod_files(only_archived)
        assert main2 is not None
        self.assertEqual(main2["file"], "only.zip", "全是归档时也要能挑出一个")

    def test_single_file_has_no_aux(self) -> None:
        main, aux = moddl.split_mod_files([_f("solo.zip", 1_000_000, 5)])
        assert main is not None
        self.assertEqual(main["file"], "solo.zip")
        self.assertEqual(aux, [])

    def test_empty_returns_none(self) -> None:
        self.assertEqual(moddl.split_mod_files([]), (None, []))


if __name__ == "__main__":
    unittest.main()
