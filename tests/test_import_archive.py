"""拖入压缩包导入的回归测试（2026-10-01）。

对应三条用户要求：

* 「一个不能确定角色名字的 mod 拖进去不会弹出角色确定窗」→ **bug 修复的回归测试**：
  导入后必须如实回报 `need_confirm` 与 `mod_id`（以前因为 Mod 列表缓存的旧数据，
  永远报"已识别"，于是永远不弹窗）；
* 「需要增加支持拖入 7z」「rar 也要」→ `.7z` / `.rar` 要被接收，不支持的格式要明确拒绝；
* 「中文拼音也要自动识别」→ 拼音目录名（含下划线/连字符写法）能识别到角色。
"""
from __future__ import annotations

import base64
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from endfieldmodcontroller import dependencies
from endfieldmodcontroller.api import EndfieldModControllerApi
from endfieldmodcontroller.config import AppConfig

MOD_INI = """
namespace = TestMod
[Constants]
global persist $x = 0
[KeyX]
key = no_modifiers VK_9
type = cycle
$x = 0,1
"""


def make_zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return path


def make_7z(target: Path, content_dir: Path) -> Path | None:
    """用可用的 7-Zip 把 ``content_dir`` 打包成 7z（bsdtar 只能读不能写，没有 7z 就跳过）。"""
    tool = dependencies.find_archive_tool()
    if not tool or tool[0] != "7z":
        return None
    result = subprocess.run(
        [tool[1], "a", "-t7z", str(target), str(content_dir)],
        capture_output=True, text=True, timeout=120,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return target if result.returncode == 0 and target.is_file() else None


class ImportArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-import-")
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.runtime / "EFMI" / "Mods"
        self.incoming = self.root / "incoming"
        self.incoming.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.json"
        self.config = AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            dependency_manifest=str(Path(__file__).resolve().parents[1] / "dependencies.json"),
        )
        self.config.save(self.config_path)
        self.api = EndfieldModControllerApi(self.config_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ------------------------------------------------------------ 工具
    def _import_chunked(self, name: str, blob: bytes) -> dict:
        """走前端真正用的分块链路：begin → chunk(1 MB) → finish。"""
        begin = self.api.import_mod_begin(name)
        self.assertTrue(begin.get("ok"), begin)
        step = 1024 * 1024
        for start in range(0, len(blob), step):
            piece = blob[start:start + step]
            part = self.api.import_mod_chunk(begin["token"], base64.b64encode(piece).decode("ascii"))
            self.assertTrue(part.get("ok"), part)
        return self.api.import_mod_finish(begin["token"])

    # ------------------------------------------------------------ 用例
    def test_zip_import_identifies_character(self) -> None:
        archive = make_zip(self.incoming / "埃特拉_泳装.zip",
                           {"埃特拉_泳装/mod.ini": MOD_INI})
        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result["group"], "埃特拉")
        self.assertFalse(result["need_confirm"])
        self.assertTrue(result["mod_id"])
        self.assertTrue((self.library / "埃特拉_泳装" / "mod.ini").is_file())

    def test_zip_import_pinyin_directory_name(self) -> None:
        """拼音写法（含下划线）也要识别到角色 —— 用户要求「中文拼音也要自动识别」。"""
        archive = make_zip(self.incoming / "Chen_Qianyu_v2.zip",
                           {"Chen_Qianyu_v2/mod.ini": MOD_INI})
        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result["group"], "陈千语")
        self.assertFalse(result["need_confirm"])

    def test_unknown_character_reports_need_confirm(self) -> None:
        """**本轮 bug 的回归测试**：认不出角色的包必须报 need_confirm=True，
        并且给出新 Mod 的 id —— 前端据此直接弹出角色确认窗。

        以前这里会拿到**导入前就缓存好的 Mod 列表**（收编流程只处理"手动放进游戏
        Mods 目录"的东西，没触发缓存失效），于是 target 永远是 None、need_confirm
        永远是 False，界面只会说"角色归属已识别"，永远不弹窗。
        """
        archive = make_zip(self.incoming / "mystery_pack_zzz.zip",
                           {"mystery_pack_zzz/mod.ini": MOD_INI})
        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result["confidence"], "none")
        self.assertTrue(result["need_confirm"], result)
        self.assertTrue(result["mod_id"], result)
        # 也必须在 pending 列表里（弹窗就是按这个列表渲染的）
        pending = self.api.pending_characters()
        ids = {item["id"] for item in pending["pending"]}
        self.assertIn(result["mod_id"], ids)
        self.assertIn(result["mod_id"], {m.id for m in self.api._mods()})

    def test_second_import_after_scan_still_reports_need_confirm(self) -> None:
        """先扫描（把缓存填满）再导入认不出的包 —— 这是用户实际操作的顺序。"""
        self.api.scan()
        archive = make_zip(self.incoming / "another_mystery.zip",
                           {"another_mystery/mod.ini": MOD_INI})
        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result["need_confirm"], result)

    def test_7z_import(self) -> None:
        """拖 .7z 要能解压进库并识别角色（用户要求「增加支持拖入 7z」）。"""
        source = self.incoming / "src_7z"
        (source / "Yvonne_bikini").mkdir(parents=True)
        (source / "Yvonne_bikini" / "mod.ini").write_text(MOD_INI, encoding="utf-8")
        archive = make_7z(self.incoming / "Yvonne_bikini.7z", source / "Yvonne_bikini")
        if archive is None:
            self.skipTest("本机没有可用的 7z 打包器（只有 bsdtar 时无法造 7z 样本）")

        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result["group"], "伊冯")
        self.assertTrue((self.library / "Yvonne_bikini" / "mod.ini").is_file())

    def test_rar_and_sevenzip_are_accepted_by_begin(self) -> None:
        """.7z / .rar 这两种后缀必须被接收（解压器的选择在落盘之后）。"""
        for name in ("pack.7z", "pack.rar", "PACK.ZIP"):
            with self.subTest(name=name):
                begin = self.api.import_mod_begin(name)
                self.assertTrue(begin.get("ok"), begin)
                self.assertEqual(begin["suffix"], "." + name.split(".")[-1].lower())

    def test_unsupported_suffix_is_rejected_clearly(self) -> None:
        for name in ("pack.tar.gz", "pack.txt", "pack"):
            with self.subTest(name=name):
                begin = self.api.import_mod_begin(name)
                self.assertFalse(begin.get("ok"), begin)
                self.assertIn(".7z", begin["message"])
                self.assertIn(".rar", begin["message"])

    def test_broken_7z_reports_readable_error(self) -> None:
        """坏包不能把进程搞崩，要如实回报**可读的中文原因**。

        ⚠️ 2026-10-03 调整断言：这种包现在会被**解压前的完整性预检**
        （`archive_check.verify_archive`）先拦住 —— 因为"文件头不对、多半没下完"
        比等解压时才抛一句 `BadZipFile` 有用得多（用户实测报过
        `解压失败：Bad CRC-32 for file '…/Endmin_HandOnCheek.dds'`：
        那种消息既没告诉他为什么、也没说该怎么办）。
        所以把"必须含『解压失败』四个字"改成"必须是**可读的中文说明**"。
        """
        blob = b"this is definitely not an archive" * 64
        result = self._import_chunked("broken.7z", blob)
        self.assertFalse(result.get("ok"), result)
        message = result["message"]
        # 仍然必须是一句**人话**（不是裸异常名 / 英文堆栈），并且要提到 7z
        self.assertIn("7z", message)
        self.assertTrue(any(ch in message for ch in "的不像完整"), message)
        self.assertFalse((self.library / "broken").exists())

    def test_archive_tool_is_discoverable(self) -> None:
        """7z/rar 的解压链至少要有一个可用实现（项目内 7z → PATH → Windows bsdtar）。"""
        tool = dependencies.find_archive_tool()
        if tool is None:
            self.skipTest("本机既没有 7-Zip 也没有 System32\\tar.exe")
        kind, exe = tool
        self.assertIn(kind, {"7z", "tar"})
        self.assertTrue(Path(exe).is_file())

    def test_zip_slip_is_rejected(self) -> None:
        """恶意 zip（条目逃出库目录）必须被拒绝，且不留下半成品目录。"""
        archive = self.incoming / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escaped.ini", "x")
        result = self._import_chunked(archive.name, archive.read_bytes())
        self.assertFalse(result.get("ok"), result)
        self.assertIn("非法路径", result["message"])
        self.assertFalse((self.library.parent / "escaped.ini").exists())
        self.assertFalse((self.library / "evil").exists())

    def test_import_cleans_temp_part(self) -> None:
        """分块临时文件跑完要删掉（别在 runtime\\_incoming 里留垃圾）。"""
        archive = make_zip(self.incoming / "tidy.zip", {"tidy/mod.ini": MOD_INI})
        self._import_chunked(archive.name, archive.read_bytes())
        inbox = self.runtime / "_incoming"
        leftovers = sorted(p.name for p in inbox.iterdir()) if inbox.is_dir() else []
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
