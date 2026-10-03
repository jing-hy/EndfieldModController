"""自更新「陈旧包」的回归测试。

对应 2026-09-30 实测 bug：`runtime\\_update\\EndfieldModController.exe` 里躺着更早下载的
0.6.0（29,445,166 B），而 `last_check.json` 的 latest 已经是 0.6.1（29,450,291 B）——
原先 `pending_payload()` **只比"latest 比当前版本新"**，于是把它当成 0.6.1 装上，
重启后还是旧版、又提示、又装；用户看到的是「拉取的都是 0.6.0」＋「反复弹弹窗」。

现在：size 不符 → 直接判 stale（`pending_payload` / `cleanup_stale` 都以此为准）；
真要安装前再核 sha256（`apply_update`），同大小不同内容也拦得住。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import selfupdate
from endfieldmodcontroller import version as version_mod
from endfieldmodcontroller.config import AppConfig


def _newer_than_current() -> str:
    """比**当前版本**大一号的版本号。

    这个测试原先写死 `latest="0.9.9"`，假设"当前版本 < 0.9.9"——2026-10-03 版本号跳到
    1.0.0 之后这个前提就失效了（"发现新版"变成"没有新版"），三个用例一起挂。
    以后一律按当前版本动态推导，升版本号不会再坏。
    """
    parts = [int(x) for x in str(version_mod.__version__).split(".") if x.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return ".".join(str(p) for p in parts)


class SelfUpdateStaleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-upd-")
        self.root = Path(self.tmp.name)
        self.config = AppConfig(
            library_dir=str(self.root / "library"),
            runtime_dir=str(self.root / "runtime"),
            builtin_runtime_dir=str(self.root / "runtime" / "builtin"),
        )
        self.config._config_path = str(self.root / "config.json")
        self.update_dir = Path(self.config.runtime_path) / "_update"
        self.update_dir.mkdir(parents=True, exist_ok=True)
        self.payload = self.update_dir / "EndfieldModController.exe"
        self.payload.write_bytes(b"MZ" + b"x" * 4094)          # 4096 字节的假"exe"
        self._write_check(latest=_newer_than_current(), size=123456, digest="sha256:" + "a" * 64)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_check(self, *, latest: str, size: int, digest: str) -> None:
        (self.update_dir / "last_check.json").write_text(json.dumps({
            "current": "0.6.1", "latest": latest, "asset_size": size, "digest": digest,
        }), encoding="utf-8")

    # ---------------------------------------------------------------- 大小不符
    def test_size_mismatch_is_stale(self) -> None:
        info = selfupdate.pending_payload(self.config)
        self.assertFalse(info["pending"])
        self.assertTrue(info["stale"])
        self.assertIn("更早版本留下的旧包", info["reason"])

    def test_cleanup_removes_stale_payload(self) -> None:
        with mock.patch.object(selfupdate, "is_frozen", return_value=False):
            removed = selfupdate.cleanup_stale(self.config)
        self.assertIn("EndfieldModController.exe", removed)
        self.assertFalse(self.payload.is_file())          # 立刻清掉，不等 7 天

    # ---------------------------------------------------------------- 大小对、内容不对
    def test_size_match_but_hash_mismatch_blocks_apply(self) -> None:
        data = b"MZ" + b"y" * (123456 - 2)
        self.payload.write_bytes(data)
        self._write_check(latest=_newer_than_current(), size=len(data), digest="sha256:" + "b" * 64)
        info = selfupdate.pending_payload(self.config)
        self.assertTrue(info["pending"])                   # 只看大小会放行（设计如此）
        current = self.update_dir / "current.exe"
        current.write_bytes(b"MZ")
        with mock.patch.object(selfupdate, "is_frozen", return_value=True), \
                mock.patch.object(selfupdate, "executable_path", return_value=current):
            result = selfupdate.apply_update(self.config, archive=str(self.payload))
        self.assertFalse(result["ok"])
        self.assertTrue(result["stale"])
        self.assertIn("sha256", result["message"])

    # ---------------------------------------------------------------- 正例
    def test_matching_payload_is_pending(self) -> None:
        data = b"MZ" + b"z" * (123456 - 2)
        self.payload.write_bytes(data)
        self._write_check(latest=_newer_than_current(), size=len(data),
                          digest="sha256:" + selfupdate._sha256(self.payload))
        info = selfupdate.pending_payload(self.config)
        self.assertTrue(info["pending"])
        self.assertFalse(info.get("stale"))

    def test_already_latest_is_not_pending(self) -> None:
        """本地已经是（或高于）latest 时，包也不该再提示 —— 老行为保持不变。"""
        self._write_check(latest="0.0.1", size=4096, digest="sha256:" + "c" * 64)
        info = selfupdate.pending_payload(self.config)
        self.assertFalse(info["pending"])
        self.assertTrue(info["stale"])


if __name__ == "__main__":
    unittest.main()
