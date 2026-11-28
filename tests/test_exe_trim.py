# SPDX-License-Identifier: AGPL-3.0-only
"""exe 体积裁剪规则（2026-11-28，用户：「现在感觉 exe 有点大，有点臃肿」）。

三条钉子：

* 角色头像 / DLSS5 组件包**不再进 exe**（改走官网直链与 assets-bundle.zip）；
* 用不到的 Python 负载（PIL._avif、webview 顺带探测进来的 twisted 等）在构建期裁掉；
* **生成的 spec 里那两条过滤函数真的会命中/放行**（不是只写了常量没人用）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _build_exe():
    spec = importlib.util.spec_from_file_location(
        "mc_build_exe", ROOT / "scripts" / "build_exe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_data_drops_avatars_and_dlss5() -> None:
    module = _build_exe()
    for edition in module.EDITIONS:
        srcs = [src.replace("\\", "/") for src, _dest in module.add_data_for(edition)]
        assert not any(src.startswith("endfieldmodcontroller/characters/") for src in srcs), (
            "角色头像不随包（用户：角色立绘可以下载后从官方拉取）")
        assert not any(src.startswith("assets/dlss5/") for src in srcs), (
            "DLSS5 组件包走 assets-bundle.zip，不再塞进 exe")

    full = [src.replace("\\", "/") for src, _dest in module.add_data_for("full")]
    lite = [src.replace("\\", "/") for src, _dest in module.add_data_for("lite")]
    # 角色**名表**仍要随包：离线也得认得出角色
    assert "endfieldmodcontroller/characters.json" in full
    assert "endfieldmodcontroller/characters.json" in lite
    # 自研面板只有完整版带
    assert "assets/addon/endfieldmodcontroller.addon64" in full
    assert "assets/addon/endfieldmodcontroller.addon64" not in lite


def test_spec_carries_the_trim_rules() -> None:
    module = _build_exe()
    text = module.render_spec(app_name="UnitTest", data_items=[], onefile=True,
                              keep_console=False)
    for prefix in module.EXCLUDED_MODULE_PREFIXES:
        assert repr(prefix) in text, f"spec 里少了模块裁剪规则 {prefix}"
    assert "a.pure = [item for item in a.pure if not _skipped(" in text
    assert "a.binaries = [item for item in a.binaries if not _skipped(" in text
    assert "a.datas = [item for item in a.datas if not _skipped(" in text
    # onefile / onedir 两种形态都得有
    assert "ONEFILE" in text and "COLLECT(" in text


def test_generated_filter_hits_and_passes() -> None:
    """把 spec 里生成的 _norm/_skipped 原样抽出来执行 —— 规则改了会在这里变红。"""
    module = _build_exe()
    text = module.render_spec(app_name="UnitTest", data_items=[], onefile=True,
                              keep_console=False)
    start = text.index("def _norm")
    end = text.index("extra = collect_all")
    namespace: dict = {}
    exec(text[start:end], namespace)  # noqa: S102 —— 就是在测生成的这段源码
    skipped = namespace["_skipped"]

    pure_skip = module.EXCLUDED_MODULE_PREFIXES
    bin_skip = module.BIN_SKIP_PREFIXES
    data_skip = module.DATA_SKIP_SUFFIXES

    # 该裁掉的
    assert skipped("PIL._avif", pure_skip)
    assert skipped("twisted.internet.defer", pure_skip)
    assert skipped("PIL\\_avif.cp314-win_amd64.pyd", bin_skip, data_skip)
    assert skipped("pythonnet\\runtime\\Python.Runtime.xml", bin_skip, data_skip)

    # 必须留下的
    assert not skipped("PIL.Image", pure_skip)
    assert not skipped("PIL\\_imaging.cp314-win_amd64.pyd", bin_skip, data_skip)
    assert not skipped("PIL\\_webp.cp314-win_amd64.pyd", bin_skip, data_skip)
    assert not skipped("webview\\lib\\runtimes\\win-x64\\native\\WebView2Loader.dll",
                       bin_skip, data_skip)
    # ★ 2026-11-28 事故回退：pywebview 在 import 阶段会枚举 runtimes/<platform>/native，
    #   删掉 arm64/x86 会让 exe 一启动就 FileNotFoundError('Cannot find win-arm64')
    assert not skipped("webview\\lib\\runtimes\\win-arm64\\native\\WebView2Loader.dll",
                       bin_skip, data_skip), "win-arm64 loader 必须留着（pywebview 启动时要枚举它）"
    assert not skipped("webview\\lib\\runtimes\\win-x86\\native\\WebView2Loader.dll",
                       bin_skip, data_skip), "win-x86 loader 必须留着（同上）"
    assert not skipped("pythonnet\\runtime\\Python.Runtime.dll", bin_skip, data_skip)
    assert not skipped("web\\index.html", bin_skip, data_skip)
    assert not skipped("assets\\addon\\endfieldmodcontroller.addon64", bin_skip, data_skip)
