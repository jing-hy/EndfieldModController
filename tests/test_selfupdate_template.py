"""自更新脚本（VBS）模板的硬约束回归测试。

为什么专门为它写测试 —— 同一个坑已经踩过两次：

* 2026-09-27：模板写成带 UTF-8 BOM → Windows Script Host 报「无效字符 800A0408」；
* 2026-10-01：往模板**注释**里写了中文 → `script.write_text(VBS_TEMPLATE, encoding="ascii")`
  抛 `UnicodeEncodeError` → 被宽泛 except 吞成「生成更新脚本失败」→ **下载成功却替换失败**，
  界面只显示「完成，但有 1 项失败」，用户完全看不出原因。

WSH 按 ANSI 读 `.vbs`，所以模板**必须纯 ASCII 且不能带 BOM**。这里把它钉死：
以后任何人改模板（包括只改注释），构建前 `python -m pytest tests -q` 会直接失败。
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest

from endfieldmodcontroller import selfupdate


class VbsTemplateTests(unittest.TestCase):
    def test_template_is_pure_ascii(self) -> None:
        """模板不能含任何非 ASCII 字符（注释也不行）。"""
        try:
            selfupdate.VBS_TEMPLATE.encode("ascii")
        except UnicodeEncodeError as exc:
            offenders = sorted({ch for ch in selfupdate.VBS_TEMPLATE if ord(ch) > 127})
            self.fail(
                "VBS 模板含非 ASCII 字符 "
                f"{offenders[:10]}（WSH 按 ANSI 读，会导致自更新替换失败）：{exc}"
            )

    def test_template_has_no_bom(self) -> None:
        self.assertFalse(selfupdate.VBS_TEMPLATE.startswith("\ufeff"), "模板首字符不能是 BOM")

    def test_template_keeps_key_logic(self) -> None:
        """关键逻辑在位：等两个进程、上限 120 秒（防止'清理注释'时误删实现）。"""
        data = selfupdate.VBS_TEMPLATE.encode("ascii")
        for needle in (b"procs.Count >= 2", b"For i = 1 To 120", b"WScript.Sleep"):
            self.assertIn(needle, data, f"模板里缺少关键逻辑 {needle!r}")

    def test_written_script_has_no_bom_and_ascii_only(self) -> None:
        """真正写出来的 .vbs 必须无 BOM、可以按 ASCII 解出全部内容。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "update.vbs"
            path.write_text(selfupdate.VBS_TEMPLATE, encoding="ascii", newline="\r\n")
            raw = path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "写出的 .vbs 不能带 UTF-8 BOM")
        self.assertNotIn(b"\r\n\r\n\r\n", raw[:64], "行尾不应异常")
        self.assertEqual(raw.decode("ascii"), selfupdate.VBS_TEMPLATE.replace("\n", "\r\n"))


if __name__ == "__main__":
    unittest.main()
