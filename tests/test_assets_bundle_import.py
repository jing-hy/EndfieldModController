"""依赖页「导入依赖的随包 zip」的测试（2026-10-05 用户要求）。

用户原话：「**依赖页加入本地随包文件，可以导入本地的随包 zip**」，
随后补充：「**需要写明是依赖的随包 zip，而且也要检查**」。

场景：单文件 exe 用户本地没有 `assets\\`、从别的机器/网盘拿到了 `assets-bundle.zip`、
或从社区镜像下了单份组件 zip（`nvngx_dlssnr_310.8.SF-v2.zip`）—— 都不必再走网络。

**要守住的性质**：
* 解包**只接受** `assets/…` 下的条目，且拒绝 `..`（目录穿越）；
* ⭐ **导入前逐条校验**：manifest 要能解析、它列出的每个文件的**全部分卷都得在包里**
  —— 缺一卷就**拒绝**并列出缺什么（"导入看着成功、之后解压到处报错"是最难查的状态，
  这正是"只看文件数/总体积一定会翻车"那条教训的落点）；
* 认不出来的 zip **明确拒绝**，并把"这个文件在哪"讲出来，且写明这是**依赖组件**入口；
* **单份组件 zip** 要能按 fatbin 内含架构自动判定变体，落到候选位（与下载链路同一套机制）。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from endfieldmodcontroller import runtime_assets

from test_dlssnr_variant import SF_SMS, fake_fatbin_dll


@pytest.fixture()
def isolated_project(tmp_path, monkeypatch):
    """把"项目根"指到临时目录。

    `import_bundle` 是往 `PROJECT_ROOT` 下解包的，而 `group_root()` 还有一条
    `Path(__file__).parents[1]` 的兜底候选会命中**真实仓库** —— 所以两处都要打桩，
    否则测试会往开发机的 `assets\\` 里写文件（那是真实资产，绝不能被测试污染）。
    """
    monkeypatch.setattr(runtime_assets, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_assets, "group_root",
                        lambda config, group: tmp_path / "assets" / group)
    # ⚠️ **也要打桩 `asset_roots`**（2026-10-06）：`iter_assets()` 走的是它，
    #    而它的候选里还有 `Path(__file__).parents[1] / assets`（仓库真实目录）——
    #    只打 `PROJECT_ROOT` 挡不住那一条，测试会读到真实资产。
    monkeypatch.setattr(runtime_assets, "asset_roots",
                        lambda config, group: [tmp_path / "assets" / group])
    return tmp_path


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def _manifest(files: dict) -> bytes:
    return json.dumps({"version": 1, "group": "nvngx", "files": files},
                      ensure_ascii=False).encode()


# --------------------------------------------------------------------------- 完整包
def test_import_full_bundle(isolated_project):
    """完整资产包：校验通过 → 解出 `assets/…` 下的文件。"""
    root = isolated_project
    archive = _zip(root / "in" / "assets-bundle.zip", {
        "assets/nvngx/manifest.json": _manifest({
            "nvngx_dlss.dll": {"size": 3, "parts": ["nvngx_dlss.dll.xz"]},
        }),
        "assets/nvngx/nvngx_dlss.dll.xz": b"packed",
        "assets/dlss5/whatever.addon64": b"addon",
    })
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is True, result["message"]
    assert result["kind"] == "bundle"
    assert result["files"] == 3
    assert result["groups"] == ["nvngx"]
    assert (root / "assets" / "nvngx" / "manifest.json").is_file()


def test_import_accepts_uncompressed_asset(isolated_project):
    """manifest 声明的文件以**未压缩形态**给出也算数（不是所有包都分卷）。"""
    root = isolated_project
    archive = _zip(root / "in" / "plain.zip", {
        "assets/nvngx/manifest.json": _manifest({
            "nvngx_dlss.dll": {"size": 3, "parts": ["nvngx_dlss.dll.xz"]},
        }),
        "assets/nvngx/nvngx_dlss.dll": b"MZ...",     # 直接给未压缩的那份
    })
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is True, result["message"]


# --------------------------------------------------------------------------- 检查
def test_import_rejects_incomplete_bundle(isolated_project):
    """⭐ 缺分卷的包必须**拒绝**（用户：「而且也要检查」）—— 否则会留下半截资产。"""
    root = isolated_project
    archive = _zip(root / "in" / "half.zip", {
        "assets/nvngx/manifest.json": _manifest({
            "nvngx_dlssnr.dll": {"parts": ["nvngx_dlssnr.dll.xz.part1",
                                           "nvngx_dlssnr.dll.xz.part2"]},
        }),
        "assets/nvngx/nvngx_dlssnr.dll.xz.part1": b"half",
        # 故意不给 part2
    })
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is False
    assert "nvngx_dlssnr.dll.xz.part2" in result["message"], result["message"]
    assert "不完整" in result["message"]
    assert not (root / "assets" / "nvngx" / "manifest.json").exists(), \
        "不完整的包一个文件都不该落盘"


def test_import_rejects_bundle_without_manifest(isolated_project):
    """有 `assets/` 但没有 manifest → 不认它是"依赖的随包资产"，并写明这一点。"""
    root = isolated_project
    archive = _zip(root / "in" / "nomft.zip", {"assets/nvngx/something.bin": b"x"})
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is False
    assert "manifest.json" in result["message"]
    assert "依赖的随包" in result["message"], "提示里要写明这是依赖组件入口"
    assert not (root / "assets" / "nvngx" / "something.bin").exists()


def test_import_rejects_bundle_with_broken_manifest(isolated_project):
    root = isolated_project
    archive = _zip(root / "in" / "badmft.zip", {
        "assets/nvngx/manifest.json": b"{not json",
    })
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is False
    assert "manifest.json" in result["message"]


def test_import_ignores_traversal_entries(isolated_project):
    """⭐ 目录穿越必须被拦住，且**不写出任何越界文件**。"""
    root = isolated_project
    archive = _zip(root / "in" / "evil.zip", {
        "../evil.txt": b"nope",
        "assets/../evil2.txt": b"nope",
        "assets/nvngx/manifest.json": _manifest({"a.dll": {"parts": ["a.dll.xz"]}}),
        "assets/nvngx/a.dll.xz": b"packed",
    })
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is True, result["message"]
    assert (root / "assets" / "nvngx" / "a.dll.xz").is_file()
    assert not (root.parent / "evil.txt").exists(), "不许写到项目根之外"
    assert not (root / "assets" / "evil2.txt").exists(), "不许用 .. 绕到别处"
    assert not (root / "evil2.txt").exists()


def test_import_rejects_unrelated_zip(isolated_project):
    """不是资产包也不是组件 zip → 明确拒绝，并把文件路径写进提示。"""
    root = isolated_project
    archive = _zip(root / "in" / "random.zip", {"readme.txt": b"hello"})
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is False
    assert str(archive) in result["message"]
    assert "assets" in result["message"]


def test_import_missing_file(isolated_project):
    result = runtime_assets.import_bundle(None, isolated_project / "nope.zip")
    assert result["ok"] is False
    assert "找不到" in result["message"]


def test_import_broken_zip(isolated_project):
    root = isolated_project
    bad = root / "in" / "broken.zip"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a zip at all")
    result = runtime_assets.import_bundle(None, bad)
    assert result["ok"] is False
    assert str(bad) in result["message"]


# --------------------------------------------------------------------------- 单份组件
def test_import_runtime_zip_detects_the_variant(isolated_project):
    """⭐ 单份组件 zip：按内含架构判定变体，落到候选位（`assets\\nvngx\\`）。"""
    root = isolated_project
    payload = root / "sf.dll"
    fake_fatbin_dll(payload, SF_SMS)
    archive = _zip(root / "in" / "nvngx_dlssnr_310.8.SF-v2.zip",
                   {"nvngx_dlssnr.dll": payload.read_bytes()})
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is True, result["message"]
    assert result["kind"] == "runtime"
    assert result["variant"] == "sf"
    assert result["arch"] == SF_SMS
    landed = root / "assets" / "nvngx" / "nvngx_dlssnr.sf.dll"
    assert landed.is_file()
    assert runtime_assets.dll_architectures(landed) == set(SF_SMS)
    assert runtime_assets.variant_from_name(landed.name) == "sf"


def test_import_runtime_zip_with_unknown_arch_is_refused(isolated_project):
    """认不出架构（不是 DLSS 运行库）→ 拒绝，并说明它里面到底有什么。"""
    root = isolated_project
    archive = _zip(root / "in" / "nvngx_dlssnr_weird.zip",
                   {"nvngx_dlssnr.dll": b"MZ" + b"\x00" * 128})
    result = runtime_assets.import_bundle(None, archive)
    assert result["ok"] is False
    assert "架构" in result["message"]
    assert not (root / "assets" / "nvngx" / "nvngx_dlssnr.weird.dll").exists()


def test_imported_variant_is_picked_up_by_selection(isolated_project, monkeypatch):
    """导入的 rtx40 会被 40 系的选择逻辑**自动采用**（导入 → 无需别的操作）。"""
    from endfieldmodcontroller import deviceinfo
    from endfieldmodcontroller.config import AppConfig

    root = isolated_project
    payload = root / "rtx40.dll"
    fake_fatbin_dll(payload, [89, 120])
    archive = _zip(root / "in" / "nvngx_dlssnr_310.8.0-RTX40.zip",
                   {"nvngx_dlssnr.dll": payload.read_bytes()})
    assert runtime_assets.import_bundle(None, archive)["variant"] == "rtx40"

    monkeypatch.setattr(
        deviceinfo, "collect",
        lambda refresh=False: {"adapters": [{"name": "NVIDIA GeForce RTX 4070"}]},
    )
    assets = root / "assets" / "nvngx"
    (assets / "manifest.json").write_text('{"version": 1, "files": {}}', encoding="utf-8")
    dlss5 = root / "runtime" / "dlss5"
    dlss5.mkdir(parents=True, exist_ok=True)
    config = AppConfig(runtime_dir=str(root / "runtime"))
    config.dlss5_dir = str(dlss5)
    config.nvngx_assets_dir = str(assets)
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.effective == "rtx40"
    assert choice.source_kind == "plain"
