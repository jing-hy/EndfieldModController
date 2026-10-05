"""DLSS5 运行库"按显卡架构自动选"的测试（2026-10-05 换方案）。

**要守住的性质**：
* 判据只有一处：`deviceinfo.nvidia_sm()`（卡名 → sm）+ `runtime_assets.select_dlssnr_variant()`
  （sm → 用哪一份文件）；
* **只展开选中那一份**（"任何受支持型号一键启动步骤一致、耗时同量级"的前提）；
* 目标文件**永远叫 `nvngx_dlssnr.dll`**（NGX 与 addon 只认这个名字），变体只是"源文件名"；
* ⭐ **变体往返不抖**：40 系机器上装好 `sf` 之后，`baseline_mismatches()` 必须为空 ——
  否则会被 `repair_mismatched` 换回 `official`、下次再判不符，**每次启动来回替换 165 MB**；
* 下载来的变体（裸 dll）与随包变体（压缩分卷）**共用同一套选择/落盘逻辑**。

测试**不依赖那 165 MB 的真文件**：这里按 `dll_architectures()` 认的结构造一个最小
"fatbin DLL"（魔数 + headerSize/fatSize + entry 的 sm 字段），几 KB 就能覆盖全部判据。
"""
from __future__ import annotations

import json
import lzma
import struct
from pathlib import Path

import pytest

from endfieldmodcontroller import deviceinfo, runtime_assets
from endfieldmodcontroller.config import AppConfig

OFFICIAL_SMS = [120]
SF_SMS = [75, 86, 89, 120]
RTX40_SMS = [89, 120]


# --------------------------------------------------------------------------- 工具
def fake_fatbin_dll(path: Path, sms) -> bytes:
    """造一个只含 fatbin 记录的最小 DLL，内容够 `dll_architectures()` 认出来。

    结构照 `runtime_assets.dll_architectures()` 的判据摆：
    魔数 `0xBA55ED50` → headerSize(offset 6, u16) / fatSize(offset 8, u64) → 每个 entry
    的 entryHeaderSize(offset 4, u32) / payloadSize(offset 8, u64) / sm(offset 24, u32)。
    """
    entries = b""
    for sm in sms:
        header = bytearray(32)
        struct.pack_into("<I", header, 4, 32)      # entryHeaderSize
        struct.pack_into("<Q", header, 8, 64)      # payloadSize
        struct.pack_into("<I", header, 24, sm)     # sm 字段
        entries += bytes(header) + b"\x00" * 64
    blob = bytearray(b"MZ")
    blob += struct.pack("<I", 0xBA55ED50)
    blob += struct.pack("<H", 1)                   # version
    blob += struct.pack("<H", 16)                  # headerSize
    blob += struct.pack("<Q", len(entries))        # fatSize
    blob += entries
    data = bytes(blob)
    path.write_bytes(data)
    return data


def _packed_entry(assets: Path, name: str, data: bytes, **extra) -> dict:
    """把一份运行库压成 `.xz` 分卷并给出 manifest 条目（模拟 `pack_nvngx_assets.py`）。"""
    packed = lzma.compress(data, format=lzma.FORMAT_XZ)
    part = assets / f"{name}.xz"
    part.write_bytes(packed)
    entry = {
        "size": len(data),
        "sha256": "",
        "packed_bytes": len(packed),
        "packed_sha256": "",
        "parts": [part.name],
        "origin": "test",
    }
    entry.update(extra)
    return entry


def make_env(tmp_path: Path, *, with_sf: bool = True, with_rtx40_plain: bool = False,
             installed_sms=None, make_manifest: bool = True):
    """造一个"资产目录 + 目标目录"的环境。

    * `with_sf`：随包 sf 变体（压缩分卷）在不在；
    * `with_rtx40_plain`：下载来的 rtx40 裸 dll 在不在（走依赖页下载的形态）；
    * `installed_sms`：目标 `nvngx_dlssnr.dll` 已就位时内含的架构（None = 不预置）。
    """
    assets = tmp_path / "assets" / "nvngx"
    assets.mkdir(parents=True, exist_ok=True)
    dlss5 = tmp_path / "runtime" / "dlss5"
    dlss5.mkdir(parents=True, exist_ok=True)

    files: dict = {}
    official = fake_fatbin_dll(tmp_path / "official.dll", OFFICIAL_SMS)
    files["nvngx_dlss.dll"] = _packed_entry(assets, "nvngx_dlss.dll", b"MZ" + b"\x00" * 32)
    files["nvngx_dlssnr.dll"] = _packed_entry(
        assets, "nvngx_dlssnr.dll", official,
        install_as="nvngx_dlssnr.dll", variant="official", arch=OFFICIAL_SMS,
    )
    if with_sf:
        sf = fake_fatbin_dll(tmp_path / "sf.dll", SF_SMS)
        files["nvngx_dlssnr.sf.dll"] = _packed_entry(
            assets, "nvngx_dlssnr.sf.dll", sf,
            install_as="nvngx_dlssnr.dll", variant="sf", arch=SF_SMS,
        )
    if make_manifest:
        (assets / "manifest.json").write_text(
            json.dumps({"version": 1, "group": "nvngx", "files": files}, ensure_ascii=False),
            encoding="utf-8",
        )
    if with_rtx40_plain:
        fake_fatbin_dll(assets / "nvngx_dlssnr.rtx40.dll", RTX40_SMS)
    if installed_sms is not None:
        fake_fatbin_dll(dlss5 / runtime_assets.DLSSNR_TARGET, installed_sms)

    config = AppConfig(runtime_dir=str(tmp_path / "runtime"))
    config.dlss5_dir = str(dlss5)
    config.nvngx_assets_dir = str(assets)
    return config, assets, dlss5


def pin_gpu(monkeypatch, *names: str):
    """把显卡探测钉死（否则跑测试的人是什么卡，结论就跟着变）。"""
    monkeypatch.setattr(
        deviceinfo, "collect",
        lambda refresh=False: {"adapters": [{"name": name} for name in names]},
    )
    deviceinfo.collect(refresh=True)     # 让进程内缓存也换成打桩值


# --------------------------------------------------------------------------- 判据
def test_variant_from_name():
    assert runtime_assets.variant_from_name("nvngx_dlssnr.dll") == "official"
    assert runtime_assets.variant_from_name("nvngx_dlssnr.sf.dll") == "sf"
    assert runtime_assets.variant_from_name("nvngx_dlssnr.rtx40.dll") == "rtx40"
    assert runtime_assets.variant_from_name("nvngx_dlssnr.dll.xz") == "official"
    assert runtime_assets.variant_from_name("nvngx_dlssnr.sf.dll.xz.part1") == "sf"
    assert runtime_assets.variant_from_name("nvngx_dlss.dll") == ""
    assert runtime_assets.variant_from_name("whatever.dll") == ""


def test_variant_for_architectures():
    assert runtime_assets.variant_for_architectures({120}) == "official"
    assert runtime_assets.variant_for_architectures({89, 120}) == "rtx40"
    assert runtime_assets.variant_for_architectures({75, 86, 89, 120}) == "sf"
    assert runtime_assets.variant_for_architectures(set()) == ""


def test_dll_architectures_on_fake_fatbin(tmp_path):
    """解析器本身：假 fatbin 里放什么就认什么（真文件实测 0.1 秒、这里毫秒级）。"""
    path = tmp_path / "a.dll"
    fake_fatbin_dll(path, SF_SMS)
    assert runtime_assets.dll_architectures(path) == set(SF_SMS)
    assert runtime_assets.dll_architectures(tmp_path / "missing.dll") == set()


# --------------------------------------------------------------------------- 选择
def test_select_uses_official_on_50_series(tmp_path, monkeypatch):
    config, _assets, dlss5 = make_env(tmp_path, installed_sms=None)
    config.dlss5_dir = str(dlss5)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 5080")
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.sm == 120
    assert choice.effective == "official"
    assert choice.source_kind == "packed"


def test_select_falls_back_to_sf_when_rtx40_missing(tmp_path, monkeypatch):
    """40 系首选 rtx40，但**没下载**时回落到随包的 sf —— 且这不算"缺"（功能完整）。"""
    config, _assets, _dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.sm == 89
    assert choice.variant == "rtx40"          # 首选（deviceinfo 的建议）
    assert choice.effective == "sf"           # 实际能用的是它
    assert choice.ok


def test_select_prefers_downloaded_rtx40(tmp_path, monkeypatch):
    """一条下载来的裸 dll 到位后，40 系自动改用它（**不需要用户再做任何事**）。"""
    config, _assets, _dlss5 = make_env(tmp_path, with_rtx40_plain=True)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.effective == "rtx40"
    assert choice.source_kind == "plain"


def test_select_skips_without_tensor_core(tmp_path, monkeypatch):
    config, _assets, _dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "NVIDIA GeForce GTX 1660 SUPER")
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.sm is None
    assert not choice.ok
    assert "tensor core" in choice.reason or "RTX" in choice.reason


def test_installed_file_is_reused_without_rescanning(tmp_path, monkeypatch):
    """目标文件已经是对的那一份时（marker 在位），一键启动**不看 165 MB**、直接用它。"""
    config, _assets, dlss5 = make_env(tmp_path, installed_sms=SF_SMS)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    runtime_assets.write_dlssnr_marker(
        config, variant="sf", sm=89, path=dlss5 / runtime_assets.DLSSNR_TARGET, archs=set(SF_SMS))
    choice = runtime_assets.select_dlssnr_variant(config)      # 快路径（rescan=False）
    assert choice.source_kind == "installed"
    assert choice.effective == "sf"


# --------------------------------------------------------------------------- 落盘
def test_ensure_installs_selected_variant_as_target(tmp_path, monkeypatch):
    """**目标名永远是 `nvngx_dlssnr.dll`**，变体只体现在内容上（NGX 只认这个名字）。"""
    config, _assets, dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    result = runtime_assets.ensure_dlssnr(config, force=True, rescan=True)
    assert result.ok, result.message
    target = dlss5 / runtime_assets.DLSSNR_TARGET
    assert target.is_file()
    assert runtime_assets.dll_architectures(target) == set(SF_SMS), "40 系该拿到含 sm_89 的那份"
    assert not (dlss5 / "nvngx_dlssnr.sf.dll").exists(), "源文件名不该出现在目标目录"
    marker = runtime_assets.read_dlssnr_marker(config)
    assert marker["variant"] == "sf" and marker["sm"] == 89
    assert sorted(marker["arch"]) == sorted(SF_SMS)


def test_ensure_switches_when_file_is_wrong(tmp_path, monkeypatch):
    """目标文件是"别人的"（只含 sm_120）时，40 系会被自动换成含 sm_89 的那份。"""
    config, _assets, dlss5 = make_env(tmp_path, installed_sms=OFFICIAL_SMS)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    result = runtime_assets.ensure_dlssnr(config, force=True, rescan=True)
    assert result.ok, result.message
    assert runtime_assets.dll_architectures(dlss5 / runtime_assets.DLSSNR_TARGET) == set(SF_SMS)


# --------------------------------------------------------------------------- 基线（防抖）
def test_baseline_is_quiet_for_the_selected_variant(tmp_path, monkeypatch):
    """⭐ 死循环防护：40 系用 sf 时，基线检查**必须为空**。

    若拿固定条目（official）去比，这里会报"偏离基线" → `repair_mismatched` 换回 official
    → 下次再判不符 …… 每次启动来回替换 165 MB。
    """
    config, _assets, _dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    runtime_assets.ensure_dlssnr(config, force=True, rescan=True)
    mismatches = [m for m in runtime_assets.baseline_mismatches(config)
                  if runtime_assets.variant_from_name(str(m.get("name"))) == "sf"
                  or str(m.get("name")) == runtime_assets.DLSSNR_TARGET]
    assert mismatches == [], f"选中的变体不该被判成偏离基线：{mismatches}"


def test_baseline_flags_a_file_that_lost_our_arch(tmp_path, monkeypatch):
    """反过来：目标文件不含本机架构时，基线要能看出来（判据没被削掉）。"""
    config, _assets, dlss5 = make_env(tmp_path, installed_sms=OFFICIAL_SMS)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    # 标记成"已就位 sf"来骗过快路径 → 走慢路径必须发现它其实不含 sm_89
    runtime_assets.write_dlssnr_marker(
        config, variant="sf", sm=89, path=dlss5 / runtime_assets.DLSSNR_TARGET, archs=set(SF_SMS))
    choice = runtime_assets.select_dlssnr_variant(config, rescan=True)
    assert choice.source_kind != "installed", "真扫之后必须发现架构不符"
    assert choice.effective == "sf"


# --------------------------------------------------------------------------- 一键启动一致性
def test_ensure_all_expands_exactly_one_runtime(tmp_path, monkeypatch):
    """⭐ 步骤一致性：不论哪一代卡，`ensure_all` 都**只展开一份运行库**、且**不下载**。

    "任何受支持的型号，相同步骤一键启动"就是靠这条守住的：展开两份 = 白解压 165 MB，
    下载 = 首次启动多等几分钟。
    """
    for gpu, want in (("NVIDIA GeForce RTX 5080", "official"),
                      ("NVIDIA GeForce RTX 4070", "sf"),
                      ("NVIDIA GeForce RTX 3060", "sf"),
                      ("NVIDIA GeForce RTX 2060", "sf")):
        root = tmp_path / gpu.split()[-1]
        config, assets, dlss5 = make_env(root)
        config.dlss5_dir = str(dlss5)
        config.nvngx_assets_dir = str(assets)
        pin_gpu(monkeypatch, gpu)
        results = runtime_assets.ensure_all(config, allow_fetch=False)
        runtime_results = [r for r in results
                           if r.name == runtime_assets.DLSSNR_TARGET]
        assert len(runtime_results) == 1, f"{gpu}: 应该只有一条运行库结果"
        assert runtime_results[0].ok, f"{gpu}: {runtime_results[0].message}"
        target = dlss5 / runtime_assets.DLSSNR_TARGET
        assert target.is_file()
        want_sms = set(SF_SMS) if want == "sf" else set(OFFICIAL_SMS)
        got = runtime_assets.dll_architectures(target)
        assert want in ("official", "sf")
        # 关键：拿到的文件必须**含本机架构**
        my_sm = deviceinfo.collect()["adapters"] and deviceinfo.nvidia_sm(gpu.lower())
        assert my_sm in got, f"{gpu}: 文件架构 {sorted(got)} 不含 sm_{my_sm}（期望 {sorted(want_sms)}）"


def test_ensure_all_skips_runtime_for_unsupported(tmp_path, monkeypatch):
    """不支持的机器报 `skipped`（不是"缺失"）—— 别给 A 卡用户制造噪音。"""
    config, _assets, _dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "Intel(R) UHD Graphics 630")
    results = runtime_assets.ensure_all(config, allow_fetch=False)
    runtime_results = [r for r in results if r.name == runtime_assets.DLSSNR_TARGET]
    assert len(runtime_results) == 1
    assert runtime_results[0].status == "skipped"
    assert "tensor core" in runtime_results[0].message or "RTX" in runtime_results[0].message


def test_asset_report_marks_the_variant_in_use(tmp_path, monkeypatch):
    """依赖页状态：本机在用的变体标 `in_use`，另一份标"备用候选"（不误导成"缺失"）。"""
    config, _assets, _dlss5 = make_env(tmp_path)
    pin_gpu(monkeypatch, "NVIDIA GeForce RTX 4070")
    runtime_assets.ensure_dlssnr(config, force=True, rescan=True)
    report = runtime_assets.asset_report(config)
    assert report["nvngx:nvngx_dlssnr.sf.dll"]["in_use"] is True
    assert report["nvngx:nvngx_dlssnr.sf.dll"]["present"] is True
    assert report["nvngx:nvngx_dlssnr.dll"]["in_use"] is False
    assert report["nvngx:nvngx_dlssnr.dll"]["status"] == "备用候选"
    assert report["bundle"]["present"] is True
