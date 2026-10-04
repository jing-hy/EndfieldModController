"""文件守护（`filewatch`）的离线测试。

覆盖用户 2026-10-01 要求的那条规则：「如果某一文件老是被删掉，要在启动的时候出个
弹窗提醒用户，建议把某个文件夹加入杀毒软件白名单」——重点是**别误报**：

* 从没装过（还没下载）的文件不算"被删"；
* 只缺一次不算"老是"（更新、用户自己清理都会造成一次缺失）；
* 整组文件一起没了 → 更像用户自己清理/改名，不是安全软件删单个文件；
* 提醒过之后不要每次启动都弹。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import filewatch
from endfieldmodcontroller.config import AppConfig

TARGET = "dlss5/nvngx_dlssnr.dll"      # 最常被杀软删的那个（165 MB）
SIBLING = "dlss5/nvngx_dlss.dll"       # 同组里"还活着"的兄弟文件


class FileWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-filewatch-")
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.runtime),
            builtin_runtime_dir=str(self.runtime / "builtin"),
        )
        self.config._config_path = str(self.root / "config.json")
        self.config.dlss5_dir = str(self.runtime / "dlss5")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ---------------------------------------------------------------- helpers
    def _item(self, key: str) -> filewatch.WatchedFile:
        return next(item for item in filewatch.WATCHED if item.key == key)

    def _path(self, key: str) -> Path:
        # 用模块自己的解析（dlss5/xxmi 那两组是以 config 的 dlss5_path /
        # builtin_runtime_path 为基准的，不是 base_dir）
        return filewatch._path_for(self.config, self._item(key))

    def _touch(self, key: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def _drop(self, key: str) -> None:
        self._path(key).unlink()

    def _boot(self, name: str) -> dict:
        """模拟"又启动了一次控制器"（采样是按进程来的，所以换一个 session）。"""
        with mock.patch.object(filewatch, "_SESSION", name):
            return filewatch.scan(self.config)

    # ------------------------------------------------------------------ cases
    def test_absent_before_ever_present_is_not_counted(self) -> None:
        """从没装过 = 还没下载，不能算"被删"。"""
        self._boot("s1")
        self._boot("s2")
        self._boot("s3")
        state = filewatch.load_state(self.config)
        entry = state["files"].get(TARGET) or {}
        self.assertEqual(int(entry.get("present") or 0), 0)
        self.assertEqual(int(entry.get("missing") or 0), 0)
        self.assertIsNone(filewatch.pending(self.config))

    def test_single_missing_streak_does_not_alert(self) -> None:
        """只缺一次不提醒（更新 / 用户自己清理都会这样）。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        self._drop(TARGET)
        self._boot("s2")
        self.assertIsNone(filewatch.pending(self.config))

    def test_missing_twice_with_sibling_alive_alerts(self) -> None:
        """曾经在 + 连续两次启动都缺 + 同组还有别的文件在 → 就是被杀软删掉的特征。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        self._drop(TARGET)
        self._boot("s2")
        self.assertIsNone(filewatch.pending(self.config), "第一次缺失不该提醒")
        self._boot("s3")
        alert = filewatch.pending(self.config)
        self.assertIsNotNone(alert, "连续两次缺失应该提醒")
        keys = [item["key"] for item in alert["items"]]
        self.assertIn(TARGET, keys)
        self.assertTrue(alert["items"][0]["isolated"])
        self.assertGreaterEqual(int(alert["items"][0]["missing"]), 2)
        # 提醒里必须带上"建议加白名单的目录"
        self.assertTrue(any("dlss5" in d for d in alert["dirs"]), alert["dirs"])

    def test_whole_group_gone_is_not_treated_as_antivirus(self) -> None:
        """整组文件都没了 → 更像用户自己清理/改名备份，不要冤杀毒软件。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        self._drop(TARGET)
        self._drop(SIBLING)
        self._boot("s2")
        self._boot("s3")
        self.assertIsNone(filewatch.pending(self.config))

    def test_ack_silences_the_alert(self) -> None:
        """点过"知道了"之后不要再每次都弹。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        self._drop(TARGET)
        self._boot("s2")
        self._boot("s3")
        alert = filewatch.pending(self.config)
        self.assertIsNotNone(alert)
        filewatch.ack(self.config, [item["key"] for item in alert["items"]])
        self.assertIsNone(filewatch.pending(self.config))

    def test_scan_counts_once_per_session(self) -> None:
        """同一个进程里多次调用只算一次采样（否则计数会虚高）。"""
        self._touch(TARGET)
        with mock.patch.object(filewatch, "_SESSION", "s1"):
            filewatch.scan(self.config)
            filewatch.scan(self.config)
            filewatch.scan(self.config)
        entry = filewatch.load_state(self.config)["files"][TARGET]
        self.assertEqual(int(entry["present"]), 1)
        self.assertEqual(int(filewatch.load_state(self.config)["scans"]), 1)

    def test_reappearing_file_resets_streak(self) -> None:
        """文件被补回来（一键启动/修复）之后，计数应该回到"没缺"的状态。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        self._drop(TARGET)
        self._boot("s2")
        self._touch(TARGET)          # 补回来了
        self._boot("s3")
        entry = filewatch.load_state(self.config)["files"][TARGET]
        self.assertEqual(int(entry["streak"]), 0)
        self.assertIsNone(filewatch.pending(self.config))

    def test_status_lists_watched_files(self) -> None:
        self._touch(TARGET)
        self._boot("s1")
        report = filewatch.status(self.config)
        rows = {row["key"]: row for row in report["items"]}
        self.assertIn(TARGET, rows)
        self.assertTrue(rows[TARGET]["exists"])

    def test_disabled_variant_is_not_treated_as_deleted(self) -> None:
        """用户/我们自己主动停用（`.disabled-by-mc`）不能算"被删" —— 否则是冤案。"""
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        path = self._path(TARGET)
        path.rename(path.with_name(path.name + ".disabled-by-mc"))
        self._boot("s2")
        self._boot("s3")
        self.assertIsNone(filewatch.pending(self.config))
        entry = filewatch.load_state(self.config)["files"][TARGET]
        self.assertEqual(int(entry["missing"]), 0)
        self.assertGreaterEqual(int(entry["present"]), 2)

    def test_disabled_directory_variant_is_not_treated_as_deleted(self) -> None:
        self._touch(TARGET)
        self._touch(SIBLING)
        self._boot("s1")
        path = self._path(TARGET)
        hidden = path.parent / "_disabled"
        hidden.mkdir(parents=True, exist_ok=True)
        path.rename(hidden / path.name)
        self._boot("s2")
        self._boot("s3")
        self.assertIsNone(filewatch.pending(self.config))


class WatchScopeTests(unittest.TestCase):
    """⭐ 2026-10-04：守护范围扩到「游戏目录 + System32」之后的两条硬要求。

    用户那天问「杀毒有没有办法处理」—— 而旧范围只盯 `runtime\\` 里的 11 个文件，
    游戏目录的两个 loader 底座、以及 System32 里的转发目标（proxy **真正去加载**的地方）
    一个都没盯，正好是"游戏起不来 / 闪退"那一类事故的现场。
    """

    def test_scope_covers_game_dir_and_system32(self) -> None:
        keys = {item.key for item in filewatch.WATCHED}
        self.assertIn("game/d3dcompiler_47.dll", keys)
        self.assertIn("game/vulkan-1.dll", keys)
        self.assertIn("system32/d3dcompiler_47.dll", keys)
        self.assertIn("system32/vulkan-1.dll", keys)

    def test_unresolvable_items_are_skipped_not_counted(self) -> None:
        """★ 游戏目录探测不到时，那几项**一个计数都不动** —— 绝不当作"被删了"。

        这是这次扩展最容易出冤案的地方：`数据根\\d3dcompiler_47.dll` 是个根本不该存在的
        路径，要是退回去拼数据根，下一轮就被算成"缺了一次"，再下一轮就弹一个冤枉窗 ——
        而这套判据的价值全在"不误报"上。
        """
        import types

        from endfieldmodcontroller import reshade_integration

        with tempfile.TemporaryDirectory(prefix="mc-scope-") as tmp:
            config = types.SimpleNamespace(base_dir=Path(tmp),
                                           runtime_path=Path(tmp) / "runtime")
            with mock.patch.object(filewatch, "_SESSION", "scope-s1"), \
                 mock.patch.object(reshade_integration, "detect_game_dir", return_value=None):
                filewatch.scan(config)
                state = filewatch.load_state(config)
                pending = filewatch.pending(config)
            for key in ("game/d3dcompiler_47.dll", "game/vulkan-1.dll"):
                entry = state["files"].get(key)
                self.assertTrue(entry is None or int(entry.get("missing") or 0) == 0,
                                f"{key} 在没有游戏目录时不该被计成缺失")
            self.assertIsNone(pending, "不适用 ≠ 缺失，不该弹提醒")


if __name__ == "__main__":
    unittest.main()
