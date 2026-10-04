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


class LatestUpdateResourceListTests(unittest.TestCase):
    """⭐ 2026-10-04 用户要求的新口径：**先看"最新版需要下什么资源"，再去下载**。

    原话：「香蕉网的下载逻辑有问题，应该先去 https://gamebanana.com/mods/updates/690864 ，
    看**最新版需要下什么资源**，然后再去下载，而不是一上来就下最新的包」。
    实测那条 Mod 的最新更新（1.8.2）给出 `_aFileRowIds = [1813631, 1809855]`
    ⇒ `changescreens_182.zip`(957 MB 主包) + `_core_2.zip`(275 B 补丁)。
    """

    @staticmethod
    def _f(file_id: int, name: str, size: int, added: int, aux: bool = False) -> dict:
        entry = _f(name, size, added, aux=aux)
        entry["id"] = file_id
        return entry

    def test_required_ids_decide_the_download_set(self) -> None:
        files = [
            self._f(1809776, "characterchange_131.zip", 86_833_333, 1_788_768_520),
            self._f(1809855, "_core_2.zip", 275, 1_788_779_065, aux=True),
            self._f(1810097, "_core_ffd68.zip", 292, 1_788_798_846, aux=True),
            self._f(1813631, "changescreens_182.zip", 957_109_937, 1_789_146_861),
        ]
        main, aux = moddl.split_mod_files(files, [1813631, 1809855])
        assert main is not None
        self.assertEqual(main["file"], "changescreens_182.zip")
        self.assertEqual([f["file"] for f in aux], ["_core_2.zip"])
        # 同页面**别的模块**的大包（CharacterChange 86 MB）不会被顺手拖下来
        self.assertNotIn("characterchange_131.zip", [main["file"]] + [f["file"] for f in aux])

    def test_update_id_not_in_files_is_ignored(self) -> None:
        """清单里有、但页面上已经没有的文件（作者删了）不能把整次挑选搞崩。"""
        files = [self._f(1, "main.zip", 1000, 10), self._f(2, "patch.zip", 5, 20, aux=True)]
        main, aux = moddl.split_mod_files(files, [1, 999])
        assert main is not None
        self.assertEqual(main["file"], "main.zip")
        self.assertEqual(aux, [])

    def test_falls_back_when_no_update_record(self) -> None:
        """没有更新记录（老 Mod）时，退回"按时间挑最新主包 + 带上配套小文件"。"""
        files = [
            self._f(1, "characterchange_131.zip", 86_833_333, 100),
            self._f(2, "_core_2.zip", 275, 200, aux=True),
            self._f(3, "changescreens_182.zip", 957_109_937, 300),
        ]
        main, aux = moddl.split_mod_files(files, [])
        assert main is not None
        self.assertEqual(main["file"], "changescreens_182.zip")
        self.assertEqual([f["file"] for f in aux], ["_core_2.zip"])

    def test_updates_parsing_sorts_and_flattens_html(self) -> None:
        """`gamebanana_updates()`：最新在前、字符串 id 也认、说明压成纯文本。"""
        import json

        from endfieldmodcontroller import dependencies

        payload = {
            "_aMetadata": {"_nRecordCount": 2},
            "_aRecords": [
                {"_idRow": 1, "_sVersion": "1.0", "_sName": "old", "_tsDateAdded": 100,
                 "_sText": "", "_aFileRowIds": [], "_aFiles": []},
                {"_idRow": 2, "_sVersion": "1.1", "_sName": "new", "_tsDateAdded": 200,
                 "_sText": "<p>请把 <code>_Core.ini</code> 换成新附件<br>谢谢</p>",
                 "_aFileRowIds": [7, "8"], "_aFiles": [{"_sFile": "x.zip"}]},
            ],
        }
        original = dependencies._http_get
        dependencies._http_get = lambda *a, **k: json.dumps(payload).encode("utf-8")  # type: ignore[assignment]
        try:
            records = moddl.gamebanana_updates(123)
        finally:
            dependencies._http_get = original  # type: ignore[assignment]

        self.assertEqual([r["version"] for r in records], ["1.1", "1.0"], "最新要在最前面")
        self.assertEqual(records[0]["file_ids"], [7, 8], "字符串 id 也要认")
        self.assertEqual(records[0]["files"], ["x.zip"])
        self.assertNotIn("<", records[0]["text"])
        self.assertIn("_Core.ini", records[0]["text"])


if __name__ == "__main__":
    unittest.main()
