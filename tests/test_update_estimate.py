"""一键更新的**预估项数必须等于实际要处理的项数**（进度条分母 = 实际项数）。

2026-10-03 用户实测反馈：「一键更新完成：实际 14 项，预估 9 项（预估公式待校准）」
—— 进度条跑完后 `N/N` 会自己对齐，但**过程中分母偏小**，进度会虚高。

排查手法（可复用）：跑一次 `start_full_update(dry_run=True)` 拿到**真实的项清单**，
再与 `_estimate_update_total()` 逐项对齐。当时两条链是：

    实际 14 项 = 随包资产 5（nvngx×2 + dlss5 addon×3）
               + 内置运行时 4（XXMI / XXMI-Libs / EFMI / Poser）
               + dlss5 组件 3（reshade_base / dlss5_feed / immersse）
               + 乳摇 1 + Poser 1
    公式 15 项 = 上面全部正确，**多出来的是 `len(依赖清单) or 1`**
                 —— 依赖清单为空时 `0 or 1` 凭空加了 1 项。

⚠️ 不要用 `EndfieldModControllerApi.__new__` 绕过构造：`config` 是 property，
绕过 `__init__` 后拿到的是函数对象。这里用真实实例 + mock 模块级读函数。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from endfieldmodcontroller import api as api_mod
from endfieldmodcontroller import dlss5_fetcher

# ⚠️ 不要依赖外部数据根（`modtest\config.json` 会被"依赖清空并重新下载"删掉，
# 也会在没跑过测试的机器上不存在）。这里自己造一份最小配置，任何环境都能跑。
CONFIG = None


def _builtin_on(inst) -> None:
    """强制"用内置运行时"开关（公式里那 4 项只在这个开关打开时才算）。"""
    try:
        inst.config.use_builtin_runtime = True   # type: ignore[misc]
    except Exception:  # noqa: BLE001 - property 只读时退化为"按当前值算"
        pass


class EstimateUpdateTotalTests(unittest.TestCase):
    def setUp(self) -> None:
        import json
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "runtime").mkdir(parents=True, exist_ok=True)
        (root / "library").mkdir(parents=True, exist_ok=True)
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"data_root": "", "runtime_dir": "runtime",
                                   "library_dir": "library"}, ensure_ascii=False),
                       encoding="utf-8")
        self.inst = api_mod.EndfieldModControllerApi(str(cfg))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_empty_inputs_do_not_inflate(self):
        """⭐ 核心回归：清单/资产为空时公式不许虚增（原来 `0 or 1` 会各加 1）。"""
        _builtin_on(self.inst)
        with mock.patch.object(api_mod.runtime_assets, "manifest_entries", return_value=[]), \
             mock.patch.object(api_mod.dependencies, "load_manifest", return_value={}):
            got = self.inst._estimate_update_total()
        builtin = 4 if getattr(self.inst.config, "use_builtin_runtime", True) else 0
        expect = builtin + len(dlss5_fetcher.COMPONENTS) + 1 + 1
        self.assertEqual(got, expect, f"空输入被虚增：{got} != {expect}")

    def test_counts_match_each_part(self):
        """各项齐全时，公式 = 资产 + 内置 + dlss5 组件 + 依赖 + 乳摇 + Poser。"""
        _builtin_on(self.inst)
        with mock.patch.object(api_mod.runtime_assets, "manifest_entries",
                               return_value=[1, 2, 3, 4, 5]), \
             mock.patch.object(api_mod.dependencies, "load_manifest",
                               return_value={"a": {}, "b": {}}):
            got = self.inst._estimate_update_total()
        builtin = 4 if getattr(self.inst.config, "use_builtin_runtime", True) else 0
        expect = 5 + builtin + len(dlss5_fetcher.COMPONENTS) + 2 + 1 + 1
        self.assertEqual(got, expect)

    def test_reader_exceptions_count_as_zero(self):
        """读清单/资产抛异常时按 0 处理 —— 宁可少算，也不要凭空虚报一项。"""
        _builtin_on(self.inst)
        with mock.patch.object(api_mod.runtime_assets, "manifest_entries",
                               side_effect=OSError("boom")), \
             mock.patch.object(api_mod.dependencies, "load_manifest",
                               side_effect=OSError("boom")):
            got = self.inst._estimate_update_total()
        builtin = 4 if getattr(self.inst.config, "use_builtin_runtime", True) else 0
        self.assertEqual(got, builtin + len(dlss5_fetcher.COMPONENTS) + 1 + 1)

    def test_no_builtin_runtime_drops_the_four(self):
        """不用内置运行时时，那 4 项不该算进去。"""
        with mock.patch.object(api_mod.runtime_assets, "manifest_entries", return_value=[]), \
             mock.patch.object(api_mod.dependencies, "load_manifest", return_value={}), \
             mock.patch.object(type(self.inst.config), "use_builtin_runtime",
                               new_callable=mock.PropertyMock, return_value=False):
            got = self.inst._estimate_update_total()
        self.assertEqual(got, len(dlss5_fetcher.COMPONENTS) + 1 + 1)

    def test_never_below_one(self):
        """极端情况下分母至少是 1（进度条不能除以 0）。"""
        with mock.patch.object(api_mod.runtime_assets, "manifest_entries", return_value=[]), \
             mock.patch.object(api_mod.dependencies, "load_manifest", return_value={}), \
             mock.patch.object(dlss5_fetcher, "COMPONENTS", ()):
            self.assertGreaterEqual(self.inst._estimate_update_total(), 1)

    def test_matches_real_dry_run_shape(self):
        """与真实数据的对照：公式 = 各部分实际条数之和（用真实 config 读到的值）。"""
        real_assets = len(api_mod.runtime_assets.manifest_entries(self.inst.config))
        real_deps = len(api_mod.dependencies.load_manifest(
            self.inst.config.dependency_manifest_path))
        builtin = 4 if getattr(self.inst.config, "use_builtin_runtime", True) else 0
        expect = real_assets + builtin + len(dlss5_fetcher.COMPONENTS) + real_deps + 1 + 1
        self.assertEqual(self.inst._estimate_update_total(), expect)


if __name__ == "__main__":
    unittest.main()
