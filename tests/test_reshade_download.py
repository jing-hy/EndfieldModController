"""ReShade 下载链路的回归测试（v1.0.11 修的那一串）。

**为什么要单独一组**：2026-10-05 的 issue #14「ReShade底座无法下载」查出来是**两个
各自独立**的原因，而且同一条逻辑在项目里有**四份实现**（依赖页 / 检查更新 /
更新 ReShade 底座 / 另一条更新路）—— 只修一处，用户看到的永远是"又挂"。所以这里把
四条路各自的**判据**都钉住：

1. `reshade.me` 首页恒定返回 `HTTP 500`（正文里其实带着版本号）⇒ 抓版本号必须
   **容忍非 2xx 并读正文**，且**必须把 `tolerate_error_status=True` 传下去**
   （忘了传就等于没修，这是最容易悄悄退化的那一处）；
2. 正文也拿不到时**退回内置基线**，不许整项失败；
3. 解包**标准库 `zipfile` 优先**，`7z.exe` 只作兜底 —— 原先"第一件事就找 7z"，
   没有 7z 的机器上这两个按钮**从来没成功过**（诊断包原话：
   `ReShadeError: 7z.exe was not found`）。开发机装了 scoop 的 7z，所以本机复现不出来，
   这里用"令 `_find_7z()` 必定抛错"来等价模拟那台机器；
4. 「检查更新」里的 ReShade 段**不许因为首页 500 而整项报错**。

全部离线：不联网、不碰真实目录，路径都指到 tmp_path。
"""
from __future__ import annotations

import io
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import dependencies, dlss5_fetcher, fastnet, reshade, updates
from endfieldmodcontroller.config import AppConfig

RESHADE_DLL = b"MZ" + b"fake-reshade-64-dll" * 32


@pytest.fixture()
def env(tmp_path, monkeypatch):
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: tmp_path / "dlss5"))
    for path in (tmp_path / "runtime" / "logs", tmp_path / "dlss5"):
        path.mkdir(parents=True, exist_ok=True)
    # 线路成绩缓存**必须打桩**：真实那份 `runtime\\_net\\lines.json` 会让 resolve_lines
    # 因为"直连慢"而改变线路列表 —— 测试不该读磁盘上的真实状态（同族坑见
    # tests/test_fastnet_upsell_guard.py 里那次随机红）。
    monkeypatch.setattr(fastnet, "_remember_line", lambda *a, **k: None)
    return SimpleNamespace(tmp=tmp_path, config=config)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# ① 抓版本号：容忍 500 读正文 + 必须把开关传下去
# ---------------------------------------------------------------------------
def test_latest_version_survives_http_500(monkeypatch):
    """首页回 500 但正文里有版本号 ⇒ 照样解析出来，**并且必须传 tolerate_error_status**。"""
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return ("https://reshade.me/", b'<a href="downloads/ReShade_Setup_6.8.0_Addon.exe">')

    monkeypatch.setattr(dependencies, "_http_get", fake_get)

    assert dlss5_fetcher.reshade_latest_version() == "6.8.0"
    assert calls, "应当去抓了首页"
    assert calls[0].get("tolerate_error_status") is True, (
        "必须显式容忍非 2xx —— reshade.me 首页恒定 500，不传这个开关就整项失败")


def test_latest_version_picks_highest(monkeypatch):
    monkeypatch.setattr(
        dependencies, "_http_get",
        lambda url, **kw: b"ReShade_Setup_6.8.0_Addon.exe ReShade_Setup_6.10.2_Addon.exe")
    assert dlss5_fetcher.reshade_latest_version() == "6.10.2"


def test_latest_version_falls_back_when_fetch_raises(monkeypatch):
    """连正文都拿不到 ⇒ 退回内置基线，**不许抛错**（依赖页整项失败就是这么来的）。"""

    def boom(url, **kwargs):
        raise OSError("所有线路都取不到 https://reshade.me/：HTTP Error 500")

    monkeypatch.setattr(dependencies, "_http_get", boom)
    logs: list[str] = []

    assert dlss5_fetcher.reshade_latest_version(logs.append) == dlss5_fetcher.RESHADE_FALLBACK_VERSION
    assert any("基线" in line for line in logs), "退回基线要在日志里说清楚"


def test_latest_version_falls_back_when_body_has_no_version(monkeypatch):
    monkeypatch.setattr(dependencies, "_http_get", lambda url, **kw: b"<html>no version here</html>")
    assert dlss5_fetcher.reshade_latest_version() == dlss5_fetcher.RESHADE_FALLBACK_VERSION


# ---------------------------------------------------------------------------
# ② 下载通道：容忍非 2xx 时也要能把正文读出来
# ---------------------------------------------------------------------------
def _http_error(body: bytes, code: int = 500) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://reshade.me/", code, "Internal Server Error",
                                  None, io.BytesIO(body))


def test_fetch_returns_body_on_error_status_when_tolerated(monkeypatch):
    monkeypatch.setattr(fastnet, "_open", lambda url, **kw: (_ for _ in ()).throw(_http_error(b"page-body")))
    url, body = fastnet.fetch("https://reshade.me/", line_mode="direct", tolerate_error_status=True)
    assert body == b"page-body"


def test_fetch_still_fails_on_error_status_by_default(monkeypatch):
    """默认行为不许变：非 2xx 仍算线路失败（否则别处的下载会把错误页当文件存下来）。"""
    monkeypatch.setattr(fastnet, "_open", lambda url, **kw: (_ for _ in ()).throw(_http_error(b"page-body")))
    with pytest.raises(OSError):
        fastnet.fetch("https://reshade.me/", line_mode="direct")


# ---------------------------------------------------------------------------
# ③ 解包：标准库优先，没有 7z 也能装
# ---------------------------------------------------------------------------
def test_download_reshade_works_without_7z(env, monkeypatch, tmp_path):
    """**核心回归**：令 `_find_7z()` 必定抛错（= 没有 7z 的机器），安装仍须成功。"""
    def no_7z():
        raise reshade.ReShadeError("[test] 这台机器没有 7z.exe")

    monkeypatch.setattr(reshade, "_find_7z", no_7z)
    payload = _zip_bytes({"ReShade64.dll": RESHADE_DLL, "ReShade64.json": b"{}"})
    monkeypatch.setattr(reshade, "_download_setup",
                        lambda url, dest, **kw: Path(dest).write_bytes(payload))

    result = reshade.download_reshade(tmp_path / "out", "6.8.0")

    assert (tmp_path / "out" / "ReShade64.dll").read_bytes() == RESHADE_DLL
    assert (tmp_path / "out" / "ReShade64.json").read_bytes() == b"{}"
    assert result["version"] == "6.8.0" and result["dll"].endswith("ReShade64.dll")


def test_download_reshade_missing_dll_is_reported(env, monkeypatch, tmp_path):
    monkeypatch.setattr(reshade, "_download_setup",
                        lambda url, dest, **kw: Path(dest).write_bytes(_zip_bytes({"other.txt": b"x"})))
    with pytest.raises(reshade.ReShadeError):
        reshade.download_reshade(tmp_path / "out2", "6.8.0")


def test_download_reshade_uses_7z_only_as_fallback(env, monkeypatch, tmp_path):
    """不是 ZIP（老版本可能是 7z SFX）时才去找 7z —— 兜底路径不许被删掉。"""
    extract = {"called": 0}

    def fake_find_7z():
        return "7z.exe"

    def fake_run(cmd, **kwargs):
        extract["called"] += 1
        out_dir = Path([part for part in cmd if part.startswith("-o")][0][2:])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ReShade64.dll").write_bytes(RESHADE_DLL)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(reshade, "_find_7z", fake_find_7z)
    monkeypatch.setattr(reshade.subprocess, "run", fake_run)
    monkeypatch.setattr(reshade, "_download_setup",
                        lambda url, dest, **kw: Path(dest).write_bytes(b"not a zip at all"))

    reshade.download_reshade(tmp_path / "out3", "6.8.0")

    assert extract["called"] == 1
    assert (tmp_path / "out3" / "ReShade64.dll").read_bytes() == RESHADE_DLL


# ---------------------------------------------------------------------------
# ④ 另一条更新路（updates.update_reshade_base）+ 检查更新
# ---------------------------------------------------------------------------
def _fake_download_file(payload: bytes):
    """假的 `updates.download_file`：把内容写到 dest 并**返回路径**（它要的是 Path，不是字节数）。"""
    def fake(url, dest, **kwargs):
        path = Path(dest)
        path.write_bytes(payload)
        return path
    return fake


def test_update_reshade_base_works_without_7z(env, monkeypatch, tmp_path):
    monkeypatch.setattr(updates, "_find_7z", lambda: None)      # 没有 7z
    payload = _zip_bytes({"ReShade64.dll": RESHADE_DLL})
    monkeypatch.setattr(updates, "download_file", _fake_download_file(payload))
    target = env.tmp / "dlss5" / "d3d12.dll"
    target.write_bytes(b"old-d3d12")

    result = updates.update_reshade_base(env.config, "6.8.0")

    assert result["ok"] is True, result.get("message")
    assert target.read_bytes() == RESHADE_DLL
    backups = list((env.tmp / "dlss5").glob("d3d12.dll.bak-*"))
    assert backups and backups[0].read_bytes() == b"old-d3d12", "替换前必须备份旧底座"


def test_update_reshade_base_reports_non_zip_without_7z(env, monkeypatch):
    monkeypatch.setattr(updates, "_find_7z", lambda: None)
    monkeypatch.setattr(updates, "download_file", _fake_download_file(b"not a zip"))
    result = updates.update_reshade_base(env.config, "6.8.0")
    assert result["ok"] is False and "7z" in result["message"]


def test_check_updates_reshade_section_never_fails_on_homepage(env, monkeypatch):
    """首页 500 时的完整效果：ReShade 那一段**不再出现 error**，且给出可下载的地址。"""
    monkeypatch.setattr(dlss5_fetcher, "reshade_latest_version",
                        lambda log=None: dlss5_fetcher.RESHADE_FALLBACK_VERSION)
    monkeypatch.setattr(updates, "component_versions",
                        lambda config: {"reshade": {"version": "6.8.0.2155"}})
    # 其它段不许联网（本测试只关心 ReShade 那一段）
    from endfieldmodcontroller import github

    monkeypatch.setattr(github, "releases_latest", lambda *a, **k: {"tag_name": "v0", "assets": []})
    monkeypatch.setattr(updates, "_fetch_json", lambda url: [])

    report = updates.check_updates(env.config)

    assert not any("ReShade" in str(item) for item in report["errors"]), report["errors"]
    assert report["reshade"]["latest"] == "6.8.0"
    assert report["reshade"]["download_url"].endswith("ReShade_Setup_6.8.0_Addon.exe")
    assert report["reshade"]["update_available"] is False      # 同号（6.8.0.2155 vs 6.8.0）不算有新版
