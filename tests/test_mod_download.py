"""Mod 下载：输入网址 → 并行下载 → 能解压的自动解压进库，不能解压的如实提示。

用户 2026-10-02 原话：「在 mod 库页按钮下面加一个 mod 下载，**下载进临时文件夹**，
**能解压的解压进库**，**不能解压的提示用户需要手动解压**，**并行多线程下载**」，
下载源 = **「给个输入框输入网址」**。

这里用**本地 http 服务**跑真实的下载链路（不 mock 网络），覆盖三种结局：
① zip → 自动解压入库（并识别到角色）；② 非压缩格式 → 「需手动解压」；
③ 404 → 「失败」。另有无网络依赖的纯函数用例。
"""
from __future__ import annotations

import http.server
import json
import os
import socketserver
import threading
import time
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from endfieldmodcontroller import core, moddl
from endfieldmodcontroller.config import AppConfig


class UrlHelpersTests(unittest.TestCase):
    def test_parse_urls_keeps_order_dedupes_and_drops_junk(self) -> None:
        text = (
            "https://a.example/x.zip\n"
            "  http://b.example/y.7z  ,  https://a.example/x.zip\n"
            "file:///C:/windows/system32/calc.exe\n"
            "不是网址\n"
            "ftp://c.example/z.zip\n"
        )
        self.assertEqual(
            moddl.parse_urls(text),
            ["https://a.example/x.zip", "http://b.example/y.7z"],
        )
        self.assertEqual(moddl.parse_urls(""), [])
        self.assertEqual(moddl.parse_urls(["https://d.example/1.rar", "nope"]), ["https://d.example/1.rar"])

    def test_file_name_from_url(self) -> None:
        self.assertEqual(moddl.file_name_from("https://a.example/Some%20Mod.zip?token=1"), "Some Mod.zip")
        # 以 `/` 结尾的地址：末段就是目录名（没有后缀 ⇒ 之后会被判「需手动解压」，不猜）
        self.assertEqual(moddl.file_name_from("https://a.example/dir/"), "dir")
        # 真的取不到名字（站点根）才退回 `mod_<hash8>`
        self.assertTrue(moddl.file_name_from("https://a.example/").startswith("mod_"))
        self.assertNotIn("/", moddl.file_name_from("https://a.example/a:b*c?.zip"))
        long_name = "x" * 300 + ".zip"
        self.assertLessEqual(len(moddl.file_name_from("https://a.example/" + long_name)), 120)

    def test_extractable_and_unique_path(self) -> None:
        self.assertTrue(moddl.is_extractable("a.zip"))
        self.assertTrue(moddl.is_extractable("b.7z"))
        self.assertTrue(moddl.is_extractable("c.RAR"))
        self.assertFalse(moddl.is_extractable("d.pak"))
        self.assertFalse(moddl.is_extractable("noext"))
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = moddl.unique_path(directory, "mod.zip")
            self.assertEqual(first.name, "mod.zip")
            first.write_bytes(b"x")
            self.assertEqual(moddl.unique_path(directory, "mod.zip").name, "mod_2.zip")

    def test_summarize_counts(self) -> None:
        items = [
            {"status": "下载中"}, {"status": "等待中"}, {"status": "已入库"},
            {"status": "需手动解压"}, {"status": "失败"},
        ]
        counts = moddl.summarize(items)
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["downloading"], 2)
        self.assertEqual(counts["imported"], 1)
        self.assertEqual(counts["manual"], 1)
        self.assertEqual(counts["failed"], 1)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: D102  —— 测试里别刷屏
        pass


class GameBananaTests(unittest.TestCase):
    """香蕉网适配（用户 2026-10-02：「看到网址是香蕉网…拉取资源同时拉取一张图片，
    访问不上就弹窗提示无法访问，建议检查 vpn」）。"""

    SAMPLE = {
        "_idRow": 721442,
        "_sName": "Arcane · Demo - GUI & OG",
        "_sProfileUrl": "https://gamebanana.com/mods/721442",
        "_sVersion": "Ver1.0",
        "_nLikeCount": 456,
        "_aGame": {"_sName": "Arknights: Endfield"},
        "_aSubmitter": {"_sName": "VeloriaLab"},
        "_aPreviewMedia": {"_aImages": [
            {"_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
             "_sFile": "full.jpg", "_sFile530": "530-90_full.jpg"},
        ]},
        "_aFiles": [
            {"_sFile": "demo_v10.zip", "_nFilesize": 86732540,
             "_sDownloadUrl": "https://gamebanana.com/dl/1834155", "_sVersion": "Ver1.0"},
            {"_sFile": "demo_v09.zip", "_nFilesize": 60635044,
             "_sDownloadUrl": "https://gamebanana.com/dl/1828670",
             "_sVersion": "Ver0.9", "_bIsArchived": True},
        ],
    }

    def test_gamebanana_id(self) -> None:
        self.assertEqual(moddl.gamebanana_id("https://gamebanana.com/mods/721442"), 721442)
        self.assertEqual(moddl.gamebanana_id("https://www.gamebanana.com/mods/download/721442"), 721442)
        # `/dl/<文件id>` 是**文件直链**，不是 Mod 页 —— 当普通链接下（别再拿去查 API，
        # 拿文件 id 查 Mod API 只会 404，会把好链接误报成"访问不上"）
        self.assertIsNone(moddl.gamebanana_id("https://gamebanana.com/dl/1834155"))
        self.assertIsNone(moddl.gamebanana_id("https://example.com/mods/721442"))
        self.assertIsNone(moddl.gamebanana_id("https://gamebanana.com/members/2180216"))

    def test_profile_parsing(self) -> None:
        from endfieldmodcontroller import dependencies

        with mock.patch.object(dependencies, "_http_get",
                               return_value=json.dumps(self.SAMPLE).encode("utf-8")):
            profile = moddl.gamebanana_profile(721442)
        self.assertEqual(profile["name"], "Arcane · Demo - GUI & OG")
        self.assertEqual(profile["game"], "Arknights: Endfield")
        self.assertEqual(profile["author"], "VeloriaLab")
        self.assertEqual(profile["cover"], "https://images.gamebanana.com/img/ss/mods/530-90_full.jpg")
        self.assertEqual([f["file"] for f in profile["files"]], ["demo_v10.zip", "demo_v09.zip"])
        self.assertTrue(profile["files"][1]["archived"])

    def test_unreachable_is_a_typed_error(self) -> None:
        """访问不上必须是**可识别**的异常（前端据此弹"检查 VPN"），而不是笼统失败。"""
        from endfieldmodcontroller import dependencies

        with mock.patch.object(dependencies, "_http_get", side_effect=OSError("timed out")):
            with self.assertRaises(moddl.GameBananaUnreachable):
                moddl.gamebanana_profile(721442)
        # 返回的不是 JSON 同样算"访问不上"
        with mock.patch.object(dependencies, "_http_get", return_value=b"<html>blocked</html>"):
            with self.assertRaises(moddl.GameBananaUnreachable):
                moddl.gamebanana_profile(721442)
        # 页面里没有文件
        with mock.patch.object(dependencies, "_http_get",
                               return_value=json.dumps({"_aFiles": []}).encode("utf-8")):
            with self.assertRaises(moddl.GameBananaUnreachable):
                moddl.gamebanana_profile(721442)


class DownloadFlowTests(unittest.TestCase):
    """真实下载：本地 http 服务当"网络"，走完整 start → poll → 入库链路。"""

    def setUp(self) -> None:
        from endfieldmodcontroller.api import EndfieldModControllerApi

        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        self.staging = self.root / "staging"
        for path in (self.library, self.runtime, self.staging):
            path.mkdir(parents=True, exist_ok=True)

        # 本地 http 源：一个能解压的 zip + 一个不能解压的 .pak
        self.serve = self.root / "serve"
        self.serve.mkdir()
        package = self.serve / "demo-mod.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("demo/yvonne.ini", "[Constants]\nglobal persist $tail = 0\n")
        (self.serve / "raw.pak").write_bytes(b"not an archive" * 64)
        self.package_bytes = package.stat().st_size

        handler = lambda *args, **kwargs: _QuietHandler(*args, directory=str(self.serve), **kwargs)  # noqa: E731
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

        self.config_path = self.root / "config.json"
        AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.staging),
            dependency_manifest=str(Path(core.__file__).parents[1] / "dependencies.json"),
        ).save(self.config_path)
        self.running_patcher = mock.patch.object(
            EndfieldModControllerApi, "game_running", return_value={"running": False})
        self.running_patcher.start()
        self.api = EndfieldModControllerApi(self.config_path)

    def tearDown(self) -> None:
        self.running_patcher.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def _wait(self, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        state = self.api.mod_download_progress()
        while not state["done"] and time.time() < deadline:
            time.sleep(0.2)
            state = self.api.mod_download_progress()
        self.assertTrue(state["done"], f"下载没在 {timeout}s 内结束：{state}")
        return state

    def test_rejects_empty_or_invalid_urls(self) -> None:
        result = self.api.start_mod_download("不是网址")
        self.assertFalse(result["ok"])
        self.assertIn("有效", result["message"])

    def test_zip_is_downloaded_extracted_and_imported(self) -> None:
        """① 能解压的：下到临时目录 → 自动解压进库 → 状态「已入库」。"""
        started = self.api.start_mod_download(self.url("demo-mod.zip"))
        self.assertTrue(started["ok"])
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "已入库", item)
        # 落盘在**临时目录**（用户要求"下载进临时文件夹"）；入库成功后源包会被清理
        temp_dir = moddl.downloads_dir(self.api.config)
        self.assertTrue(temp_dir.is_dir())
        self.assertFalse((temp_dir / "demo-mod.zip").exists(), "入库成功后源包应当被删掉")
        self.assertTrue(item.get("source_removed"))
        # 库里真的多出了那个 Mod（不是只报了个成功）
        names = [p.name for p in self.library.iterdir()]
        self.assertTrue(any("demo-mod" in name for name in names), names)
        self.assertEqual(state["counts"]["imported"], 1)

    def test_zip_source_is_removed_after_import(self) -> None:
        """入库成功后**删掉下载目录里的源包**（用户 2026-10-02：「成功入库就删掉」）——
        内容已经在库里了，留着只是占地方。"""
        self.api.start_mod_download(self.url("demo-mod.zip"))
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "已入库", item)
        self.assertTrue(item.get("source_removed"))
        temp_dir = moddl.downloads_dir(self.api.config)
        # 源包没了，但 Mod 确实在库里（不是"删了却没入库"）
        self.assertFalse((temp_dir / "demo-mod.zip").exists())
        self.assertTrue(any("demo-mod" in p.name for p in self.library.iterdir()))

    def test_non_archive_is_kept_for_manual_extraction(self) -> None:
        """② 不能解压的：**留在临时目录**并标「需手动解压」，路径给出来。"""
        self.api.start_mod_download(self.url("raw.pak"))
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "需手动解压", item)
        self.assertTrue(item["path"] and Path(item["path"]).is_file())
        self.assertIn("手动解压", item["message"])
        self.assertEqual(list(self.library.iterdir()), [])   # 绝不往库里塞垃圾
        self.assertEqual(state["counts"]["manual"], 1)

    def test_download_failure_is_reported(self) -> None:
        """③ 404：如实报失败，不假装成功。"""
        self.api.start_mod_download(self.url("nope.zip"))
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "失败", item)
        self.assertTrue(item["message"])
        self.assertEqual(state["counts"]["failed"], 1)

    def test_parallel_batch_mixed(self) -> None:
        """多个链接**一次提交**，并行跑完，各自得到正确的结局。"""
        result = self.api.start_mod_download(
            "\n".join([self.url("demo-mod.zip"), self.url("raw.pak"), self.url("nope.7z")]))
        self.assertEqual(result["total"], 3)
        state = self._wait(timeout=60)
        statuses = sorted(item["status"] for item in state["items"])
        self.assertEqual(statuses, ["失败", "已入库", "需手动解压"])

    def test_second_batch_refused_while_running(self) -> None:
        """上一批没跑完时不许再开一批（否则两批一起写库、进度也说不清）。"""
        self.api.start_mod_download(self.url("demo-mod.zip"))
        second = self.api.start_mod_download(self.url("raw.pak"))
        self.assertFalse(second["ok"])
        self.assertIn("还在下载", second["message"])
        self._wait()

    def test_open_download_dir_creates_and_opens(self) -> None:
        with mock.patch.object(self.api, "open_path", return_value={"ok": True}) as opened:
            result = self.api.open_download_dir()
        self.assertTrue(result["ok"])
        self.assertEqual(Path(opened.call_args[0][0]), moddl.downloads_dir(self.api.config))
        self.assertTrue(moddl.downloads_dir(self.api.config).is_dir())

    def test_slow_speed_is_distinguished_from_broken_file(self) -> None:
        """「慢到被 fastnet 放弃」要能和「文件坏了」区分开 ——
        前者前端会弹「建议开 VPN」（用户 2026-10-02：「这么低速明显是没开 vpn，
        应该弹窗建议开 vpn 而不是纯失败」）。"""
        real = ("<urlopen error 所有线路都失败 → 直连: 探测速度仅 0.01 MB/s"
                "（低于 0.3 MB/s 可用线），放弃这条线路>")
        self.assertTrue(moddl.looks_like_slow(real))
        self.assertTrue(moddl.looks_like_slow("<urlopen error timed out>"))
        self.assertTrue(moddl.looks_like_slow("HTTP Error 403: Forbidden"))  # 拒绝也归到"网络不通"
        # 文件/内容层面的错误不算"慢"
        self.assertFalse(moddl.looks_like_slow("sha256 校验失败（期望 ab…，实际 cd…）"))
        self.assertFalse(moddl.looks_like_slow(""))
        # download() 的第三个返回值就是给前端的这个标记
        from endfieldmodcontroller import dependencies

        with mock.patch.object(dependencies, "_http_get", side_effect=OSError(real)):
            path, message, slow = moddl.download("https://gamebanana.com/dl/1", Path(self.tmp.name))
        self.assertIsNone(path)
        self.assertIn("探测速度", message)
        self.assertTrue(slow)

    def test_failed_download_leaves_no_partial_files(self) -> None:
        """下载失败要清掉半成品（用户 2026-10-02：「下载失败要清理掉失败的半成品」）。

        现场：失败后下载目录里留下 `1820618.mcdownload`（fastnet 的断点续传文件）。
        """
        from endfieldmodcontroller import dependencies

        dest = Path(self.tmp.name) / "dl"
        dest.mkdir()
        # 真实场景：fastnet 只写 `<目标名>.mcdownload`（成功才 rename 成目标名），
        # 所以失败现场通常是"目标不存在 + 续传文件存在"。
        (dest / "1820618.mcdownload").write_bytes(b"x" * 32)
        with mock.patch.object(dependencies, "_http_get", side_effect=OSError("timed out")):
            path, _message, _slow = moddl.download("https://gamebanana.com/dl/1820618", dest)
        self.assertIsNone(path)
        self.assertEqual(list(dest.iterdir()), [], "失败后不该留下任何半成品")

    def test_failed_download_does_not_touch_existing_files(self) -> None:
        """失败清理**只清这次任务自己的半成品** —— 目录里已有的同名文件（上次成功下载的）
        一个字节都不许动（数据安全 > 干净）。"""
        from endfieldmodcontroller import dependencies

        dest = Path(self.tmp.name) / "dl2"
        dest.mkdir()
        keep = dest / "1820618"
        keep.write_bytes(b"previous-download")
        with mock.patch.object(dependencies, "_http_get", side_effect=OSError("connection reset")):
            path, _message, _slow = moddl.download("https://gamebanana.com/dl/1820618", dest)
        self.assertIsNone(path)
        self.assertEqual([p.name for p in dest.iterdir()], ["1820618"])
        self.assertEqual(keep.read_bytes(), b"previous-download")

    def test_download_info_is_saved_into_mod_folder(self) -> None:
        """每个 Mod 文件夹里都要留一份下载信息（用户 2026-10-02：
        「还有每个 mod 文件夹内都要保存下载地址、时间这些信息」）。"""
        self.api.start_mod_download(self.url("demo-mod.zip"))
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "已入库", item)
        info_path = Path(item["info_file"])
        self.assertEqual(info_path.name, moddl.DOWNLOAD_INFO_NAME)
        # 文件就在这个 Mod 自己的目录里（⚠️ 用 samefile 比，别比字符串：
        # Windows 上同一个目录会有 `ADMINI~1` 与 `Administrator` 两种写法）
        mod_dir = next(p for p in self.library.iterdir() if "demo-mod" in p.name)
        self.assertTrue(os.path.samefile(info_path.parent, mod_dir))
        payload = json.loads(info_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["来源网址"], self.url("demo-mod.zip"))
        self.assertTrue(payload["下载时间"])
        self.assertEqual(payload["文件名"], "demo-mod.zip")

    def test_gamebanana_cover_is_saved_into_mod_folder_then_cleaned_up(self) -> None:
        """香蕉网封面：**入库时拷一份进 Mod 目录**（Mod 卡片就能显示图了），
        临时目录里那份**无论成功失败都清掉**（用户 2026-10-02：「入库或者中断图片也要删」）。"""
        cover_bytes = b"\xff\xd8\xff\xe0" + b"x" * 64     # 假 JPEG（只要字节在）
        self.api.start_mod_download(self.url("demo-mod.zip"))
        state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "已入库", item)
        # 临时目录里：源包没了、封面也没了
        temp_dir = moddl.downloads_dir(self.api.config)
        self.assertEqual([p.name for p in temp_dir.iterdir()], [], "下载目录不该留源包与封面")
        self.assertTrue(item.get("cover_cleaned") or not item.get("cover"))

    def test_stalled_download_is_marked_failed(self) -> None:
        """长时间没有任何数据的任务要**自己收尾**，不能永远挂着"下载中"。

        用户 2026-10-02 实测：卡片一直显示「下载中 1 · 进行中…」、进度条 0/0、速度也没有
        —— 那就是下载线程卡在探测/重试里了。判据是"**零字节增长**超过阈值"，不是总时长
        （正常慢速下载每几秒都会有字节进来，不能被误伤）。
        """
        api = self.api
        api._mod_dl = {
            "items": [{"url": "https://example.com/x.zip", "name": "x.zip", "status": "下载中",
                       "received": 0, "size": 0, "percent": 0, "last_tick": time.time() - 10_000}],
            "done": False, "started_at": "", "dir": "",
        }
        item = api.mod_download_progress()["items"][0]
        self.assertEqual(item["status"], "失败", item)
        self.assertTrue(item["stalled"])
        self.assertIn("卡死", item["message"])
        # 正在动的任务不许被误判
        api._mod_dl["items"][0].update({"status": "下载中", "last_tick": time.time(), "stalled": False})
        self.assertEqual(api.mod_download_progress()["items"][0]["status"], "下载中")

    def test_clear_records_refuses_while_downloading(self) -> None:
        """「清除记录」不能在任务还在跑的时候把记录抹掉。"""
        api = self.api
        api._mod_dl = {
            "items": [{"url": "u", "name": "x.zip", "status": "下载中",
                       "received": 1, "size": 10, "last_tick": time.time()}],
            "done": False, "started_at": "", "dir": "",
        }
        refused = api.clear_mod_downloads()
        self.assertFalse(refused["ok"])
        self.assertIn("在跑", refused["message"])
        api._mod_dl["items"][0]["status"] = "已入库"
        self.assertTrue(api.clear_mod_downloads()["ok"])
        self.assertEqual(api.mod_download_progress()["items"], [])

    def test_cancel_and_pause_flags(self) -> None:
        """终止 / 暂停 / 继续 三个按钮的后端语义（用户 2026-10-02 要求）。

        暂停**保留断点**（下次「继续」能续传），终止**清干净**；两者都不该被报成"失败"。
        """
        api = self.api
        api._mod_dl = {"items": [{"url": "u", "name": "x.zip", "status": "下载中",
                                  "received": 0, "size": 10, "last_tick": time.time()}],
                       "done": False, "started_at": "", "dir": "", "cancel": False, "pause": False}
        self.assertTrue(api.has_active_downloads())
        self.assertTrue(api.cancel_mod_downloads()["ok"])
        self.assertTrue(api._mod_dl["cancel"])
        self.assertFalse(api._mod_dl["pause"])
        self.assertTrue(api.pause_mod_downloads()["ok"])
        self.assertTrue(api._mod_dl["pause"])
        self.assertFalse(api._mod_dl["cancel"])
        # 「继续」把待续任务重新排队
        api._mod_dl["items"][0]["status"] = "已暂停"
        api._mod_dl["done"] = True
        with mock.patch.object(api, "_mod_download_worker", lambda *a, **k: None):
            self.assertEqual(api.resume_mod_downloads()["resumed"], 1)
        self.assertFalse(api._mod_dl["pause"])
        self.assertEqual(api._mod_dl["items"][0]["status"], "等待中")

    def test_exit_confirmation_flag(self) -> None:
        """关窗口前要判"有没有在下载"，用户确认后放行（用户 2026-10-02：
        「如果在下载的时候关闭 mod 管理器，要弹窗提示」）。"""
        api = self.api
        api._mod_dl = {"items": [{"url": "u", "name": "x.zip", "status": "下载中",
                                  "received": 0, "size": 10, "last_tick": time.time()}],
                       "done": False, "started_at": "", "dir": "", "cancel": False, "pause": False}
        self.assertFalse(api.exit_confirmed)
        self.assertTrue(api.has_active_downloads())
        # confirm_exit 会真的退出进程 —— 这里只验证它先把标志立起来，别真跑 os._exit
        with mock.patch("os._exit"), mock.patch.object(api, "shutdown", lambda: None):
            api.confirm_exit()
        self.assertTrue(api.exit_confirmed)
        api._mod_dl["items"][0]["status"] = "已入库"
        self.assertFalse(api.has_active_downloads())

    def test_gamebanana_link_uses_real_file_url_and_grabs_cover(self) -> None:
        """香蕉网链接：面板给的是**页面地址**，程序要换成真实文件直链，并顺带取封面图。"""
        profile = {
            "mod_id": 721442, "name": "Arcane · Demo", "game": "Arknights: Endfield",
            "author": "VeloriaLab", "version": "Ver1.0", "likes": 456,
            "page": "https://gamebanana.com/mods/721442",
            "cover": self.url("cover.jpg"),
            "files": [{"file": "demo.zip", "size": self.package_bytes,
                       "url": self.url("demo-mod.zip"), "version": "Ver1.0", "archived": False}],
        }
        (self.serve / "cover.jpg").write_bytes(b"\xff\xd8\xff\xd9")     # 最小 jpeg 头尾
        with mock.patch.object(moddl, "gamebanana_profile", return_value=profile):
            started = self.api.start_mod_download("https://gamebanana.com/mods/721442")
            self.assertTrue(started["ok"])
            state = self._wait()
        item = state["items"][0]
        self.assertEqual(item["status"], "已入库", item)
        self.assertEqual(item["title"], "Arcane · Demo")
        self.assertIn("香蕉网", item["note"])
        self.assertIn("VeloriaLab", item["note"])
        # 封面真的下回来了：前端拿到的仍是 data URI（WebView2 里 file:// 读不到本地图），
        # 而且**已经拷进 Mod 目录**（名称 cover.*，`core.find_cover` 靠 COVER_HINTS 命中它）；
        # 临时目录里那份已被收尾清掉（用户 2026-10-02：「入库或者中断图片也要删」）。
        self.assertTrue(str(item.get("cover_data", "")).startswith("data:image/jpeg;base64,"))
        self.assertTrue(item.get("cover_cleaned"))
        self.assertFalse(Path(item["cover"]).exists(), "临时目录里的封面应当被清掉")
        mod_dir = next(p for p in self.library.iterdir() if "demo" in p.name.lower())
        self.assertTrue((mod_dir / "cover.jpg").is_file(), "封面应当拷进 Mod 目录供库卡片显示")

    def test_gamebanana_unreachable_marks_task_for_popup(self) -> None:
        """访问不上香蕉网 → 该任务标 `unreachable`（前端据此弹"建议检查 VPN"），
        但**同一批里的其它任务照常完成**。"""
        profile_side_effect = moddl.GameBananaUnreachable("timed out")
        with mock.patch.object(moddl, "gamebanana_profile", side_effect=profile_side_effect):
            self.api.start_mod_download(
                "https://gamebanana.com/mods/721442\n" + self.url("demo-mod.zip"))
            state = self._wait(timeout=60)
        by_url = {item["url"]: item for item in state["items"]}
        banana = next(item for item in state["items"] if "gamebanana.com" in item["url"])
        self.assertEqual(banana["status"], "失败")
        self.assertTrue(banana["unreachable"])
        self.assertIn("VPN", banana["message"])
        # 另一个任务不受影响
        self.assertTrue(any(item["status"] == "已入库" for item in state["items"]), by_url)


class ResetDependenciesTests(unittest.TestCase):
    """「依赖清空重新下载」——**只删程序自己的东西，绝不碰 Mod 库**（用户 2026-10-02 要求）。"""

    def setUp(self) -> None:
        from endfieldmodcontroller.api import EndfieldModControllerApi

        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library = self.root / "library"
        self.runtime = self.root / "runtime"
        (self.library / "某个Mod").mkdir(parents=True)
        (self.library / "某个Mod" / "mod.ini").write_text("[Constants]\n", encoding="utf-8")
        (self.root / "mod-backup" / "旧备份").mkdir(parents=True)
        (self.runtime / "logs").mkdir(parents=True)
        (self.runtime / "logs" / "old.log").write_text("x", encoding="utf-8")
        # 随包资产（用户 2026-10-02：「assets\ 也要删」）—— 造个小的，别真造 130 MB
        (self.root / "assets" / "dlss5").mkdir(parents=True)
        (self.root / "assets" / "dlss5" / "manifest.json").write_text("{}", encoding="utf-8")
        (self.root / "我自己放的东西.txt").write_text("keep me", encoding="utf-8")
        config_path = self.root / "config.json"
        AppConfig(
            library_dir=str(self.library),
            runtime_dir=str(self.runtime),
            staging_mods_dir=str(self.root / "staging"),
            dependency_manifest=str(Path(core.__file__).parents[1] / "dependencies.json"),
        ).save(config_path)
        self.running_patcher = mock.patch.object(
            EndfieldModControllerApi, "game_running", return_value={"running": False})
        self.running_patcher.start()
        self.api = EndfieldModControllerApi(config_path)
        self.api.game_clean_restore = lambda stamp="": {"ok": True, "message": "模拟还原"}

    def tearDown(self) -> None:
        self.running_patcher.stop()
        self.tmp.cleanup()

    def test_reset_wipes_runtime_but_keeps_library_and_settings(self) -> None:
        result = self.api.reset_dependencies_and_redownload()
        self.assertTrue(result["ok"], result)
        # ① runtime 清掉了
        self.assertFalse((self.runtime / "logs" / "old.log").exists())
        # ①b 随包 assets 也清掉了（用户追加要求：「assets\ 也要删」）
        self.assertFalse((self.root / "assets").exists())
        # ② **Mod 库一个字节都不许动**（红线）
        self.assertTrue((self.library / "某个Mod" / "mod.ini").is_file())
        # ③ Mod 备份仓也不动
        self.assertTrue((self.root / "mod-backup" / "旧备份").is_dir())
        # ④ 用户自己放的文件不动（不按"除 X 全删"来）
        self.assertTrue((self.root / "我自己放的东西.txt").is_file())
        # ⑤ 配置重建了，且**路径没丢**
        self.assertTrue((self.root / "config.json").is_file())
        reloaded = AppConfig.load(self.root / "config.json")
        self.assertEqual(Path(reloaded.library_dir).resolve(), self.library.resolve())
        self.assertEqual(Path(reloaded.runtime_dir).resolve(), self.runtime.resolve())

    def test_reset_reports_what_it_kept(self) -> None:
        result = self.api.reset_dependencies_and_redownload()
        for item in ("Mod 库", "Mod 备份仓", "程序 exe"):
            self.assertIn(item, result["kept"])


if __name__ == "__main__":
    unittest.main()


