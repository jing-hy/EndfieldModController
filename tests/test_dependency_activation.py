"""依赖的「按需激活 + 去重 + 内外优先级」（用户 2026-10-02 要求）。

用户原话：「加个去重，在设置里加个**内部 RabbitFX 优先，默认开**，开的话如果还有外部
RabbitFX 就把**外部的屏蔽掉**，没开就把**内部屏蔽掉、就算外部优先**，如果**外部有多个，
按最后安装的优先**。」

同时钉住 2026-10-02 修掉的那个断点：**决定"要不要下载依赖"和"要不要激活依赖"必须用
同一套判据** —— 以前激活侧只读 sidecar 的 `requires`（库里几乎没人写），而下载侧会扫 ini
文本，于是依赖"下得来、进不去"。
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from endfieldmodcontroller import activation, core

# 模拟"佩丽卡 OL 装"：**没有 sidecar**，只在 ini 文本里引用 RabbitFX
SKIN_INI = (
    "namespace = Demo\n"
    "[TextureOverrideSkin]\n"
    "hash = 12345678\n"
    "Resource\\RabbitFX\\FXMap = ref Resource-mask\n"
    "run = CommandList\\RabbitFX\\SetTextures\n"
)
DEP_INI = "namespace = RabbitFX\n[Constants]\nglobal persist $censor = 0\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DependencyActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="mc-depact-")
        self.root = Path(self.tmp.name)
        self.lib = self.root / "library"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # -- 构造 --------------------------------------------------------
    def _skin(self) -> Path:
        target = self.lib / "佩丽卡" / "佩丽卡-OL装"
        _write(target / "0.ini", SKIN_INI)
        return target

    def _internal_rabbitfx(self, name: str = "RabbitFX") -> Path:
        target = self.lib / "_deps" / name
        _write(target / "RabbitFX.ini", DEP_INI)
        return target

    def _external_rabbitfx(self, folder: str, inner: str = "RabbitFX -ENDMI-") -> Path:
        """外部依赖 = 用户手动导入库的（名字常带前缀、里层还套一层）。"""
        target = self.lib / folder / inner
        _write(target / "RabbitFX.ini", DEP_INI)
        return target

    def _resolve(self, prefer_internal: bool = True):
        mods = core.scan_library(self.lib, self.lib)
        return activation.resolve_active_set(
            mods, [m.id for m in mods], prefer_internal_dependencies=prefer_internal
        )

    # -- 测试 --------------------------------------------------------
    def test_ini_reference_activates_internal_dependency(self) -> None:
        """核心修复：ini 里引用了 RabbitFX（sidecar 里没写）也必须把它激活。"""
        self._skin()
        self._internal_rabbitfx()
        active, report = self._resolve()
        self.assertIn("RabbitFX", [m.name for m in active], report.to_dict())
        self.assertEqual(list(report.dependency_choices), ["rabbitfx"])
        self.assertEqual(report.missing_dependencies, [])

    def test_comment_mention_is_not_a_dependency_reference(self) -> None:
        """**只在注释里提到依赖 ≠ 依赖它**（2026-10-02 现场定案）。

        庄方宜旗袍的 ini 里有一句注释「Draw-local isolation from optional RabbitFX
        bindings」—— 它其实是在声明"**本 Mod 不依赖** RabbitFX"，而早期判据扫的是 ini
        **全文** ⇒ 误把 RabbitFX 激活进 staging ⇒ 游戏启动几十秒后崩在着色器编译器。
        用户移走 RabbitFX 之后：「**现在可以进入了，确认生效**」。
        """
        target = self.lib / "庄方宜" / "旗袍"
        _write(
            target / "mod.ini",
            "namespace = demo\n"
            "[TextureOverrideBody]\n"
            "hash = 12345678\n"
            "; Draw-local isolation from optional RabbitFX bindings.\n",
        )
        self._external_rabbitfx("（重要前置）RabbitFX v24_3d366")
        active, report = self._resolve()
        self.assertNotIn(
            "RabbitFX -ENDMI-", [m.name for m in active],
            "注释里提到 RabbitFX 不该被当成依赖引用",
        )
        self.assertEqual(list(report.dependency_choices), [])

    def test_manual_imported_dependency_is_found_by_name_containment(self) -> None:
        """用户手动导入的（`（重要前置）RabbitFX …` / 里层 `RabbitFX -ENDMI-`）也要能命中。"""
        self._skin()
        self._external_rabbitfx("（重要前置）RabbitFX v24_3d366")
        active, report = self._resolve()
        self.assertIn("RabbitFX -ENDMI-", [m.name for m in active], report.to_dict())

    def test_internal_wins_by_default_and_external_is_blocked(self) -> None:
        self._skin()
        self._internal_rabbitfx()
        self._external_rabbitfx("（重要前置）RabbitFX v24_3d366")
        active, report = self._resolve(prefer_internal=True)
        names = [m.name for m in active]
        self.assertIn("RabbitFX", names)
        self.assertNotIn("RabbitFX -ENDMI-", names, "开了内部优先，外部不该进 staging")
        self.assertTrue(report.blocked_dependencies, report.to_dict())
        self.assertIn("屏蔽外部", report.blocked_dependencies[0]["reason"])

    def test_external_wins_when_switch_is_off(self) -> None:
        self._skin()
        self._internal_rabbitfx()
        self._external_rabbitfx("（重要前置）RabbitFX v24_3d366")
        active, report = self._resolve(prefer_internal=False)
        names = [m.name for m in active]
        self.assertIn("RabbitFX -ENDMI-", names)
        self.assertNotIn("RabbitFX", names, "关掉内部优先后，内部那份不该进 staging")
        self.assertIn("屏蔽内部", report.blocked_dependencies[0]["reason"])

    def test_multiple_externals_keep_the_last_installed(self) -> None:
        """外部有多个 → 按"最后安装的"（目录创建时间）取一份，其余屏蔽。"""
        self._skin()
        self._external_rabbitfx("（重要前置）RabbitFX 旧", "RabbitFX-old")
        time.sleep(0.05)        # 让"后安装的"在创建时间上真的更晚（判据就是创建时间）
        self._external_rabbitfx("（重要前置）RabbitFX 新", "RabbitFX-new")
        active, report = self._resolve(prefer_internal=False)
        names = [m.name for m in active]
        self.assertIn("RabbitFX-new", names)
        self.assertNotIn("RabbitFX-old", names)
        self.assertEqual([m.name for m in active if m.is_dependency], ["RabbitFX-new"])

    def test_multiple_internals_keep_the_last_installed(self) -> None:
        self._skin()
        self._internal_rabbitfx()
        time.sleep(0.05)
        self._internal_rabbitfx("RabbitFX-copy")
        active, report = self._resolve()
        deps = [m for m in active if m.is_dependency]
        self.assertEqual(len(deps), 1, [m.name for m in deps])
        self.assertEqual(deps[0].name, "RabbitFX-copy", "应取最后安装的那份")

    def test_only_one_dependency_instance_ever_reaches_staging(self) -> None:
        """作者红线：rabbitfx 永远只有一份进 staging（多个实例会导致游戏崩溃）。"""
        self._skin()
        self._internal_rabbitfx()
        self._external_rabbitfx("外部A", "RabbitFX-a")
        self._external_rabbitfx("外部B", "RabbitFX-b")
        for prefer in (True, False):
            active, _report = self._resolve(prefer_internal=prefer)
            deps = [m for m in active if m.is_dependency]
            self.assertEqual(len(deps), 1, f"prefer_internal={prefer}: {[m.name for m in deps]}")

    def test_mod_without_reference_pulls_no_dependency(self) -> None:
        """没引用依赖的 Mod 不该被硬塞依赖（2026-09-27 那场闪退的根因）。"""
        target = self.lib / "某角色" / "普通皮肤"
        _write(target / "0.ini", "namespace = Demo\n[TextureOverrideY]\nhash = deadbeef\n")
        self._internal_rabbitfx()
        active, report = self._resolve()
        self.assertEqual([m.name for m in active if m.is_dependency], [])
        self.assertEqual(report.dependencies, [])

    def test_missing_dependency_is_reported(self) -> None:
        """引用了但库里没有 → 如实报缺失（不假装成功）。"""
        self._skin()
        active, report = self._resolve()
        self.assertEqual([m.name for m in active if m.is_dependency], [])
        self.assertTrue(any("rabbitfx" in str(x).lower() for x in report.missing_dependencies),
                        report.to_dict())


if __name__ == "__main__":
    unittest.main()
