# SPDX-License-Identifier: GPL-3.0-or-later
"""镜像**假包**与**日志自相矛盾**的回归测试（2026-11-07 实测报障）。

用户两条原话：
1. 「为什么现在速度掉到 4k 了？」（前置现场：ghproxy.net 下到一半 sha256 不符 ⇒ 白等）
2. 「多线路动态抢块已启用（不含直连）」下一行却是「尝试线路：直连」—— 自己看着都绕

根因①：一批镜像对 Release 资产返回 **HTTP 200 + text/html**（错误页/限流页），
        旧代码只问"下完了吗"，于是把网页当 zip 下完、最后才 sha256 不符。
根因②：抢块池的日志说的是"池子里有谁"，而直连仍会按顺序先做单连接尝试；
        措辞写成「已启用…不含直连」就会和下一行"尝试线路：直连"打架。
根因③：慢线路那段**先打一行「仍用 12 连接试」**，随后 ② 又把线程数重算成 8 ——
        两个数字同时出现在日志里。
"""
from __future__ import annotations

import pytest

from endfieldmodcontroller import fastnet


# ---------------------------------------------------------------- 假包判据
def test_html_page_is_rejected_as_payload() -> None:
    ok, why = fastnet.validate_payload(b"<!DOCTYPE html><html>...", "text/html", "x.zip")
    assert not ok, "镜像返回网页时必须判死，不能当安装包下完"
    assert "网页" in why or "HTML" in why


def test_html_sniffing_works_even_without_content_type() -> None:
    """有些镜像连 Content-Type 都是 octet-stream，只能靠首字节认出来。"""
    ok, _why = fastnet.validate_payload(b"  <html><body>429</body></html>",
                                        "application/octet-stream", "pkg.zip")
    assert not ok


def test_real_zip_and_exe_are_accepted() -> None:
    assert fastnet.validate_payload(b"PK\x03\x04rest", "application/zip", "a.zip")[0]
    assert fastnet.validate_payload(b"MZ\x90\x00", "application/octet-stream", "b.exe")[0]


def test_wrong_magic_for_zip_is_rejected() -> None:
    ok, why = fastnet.validate_payload(b"\x1f\x8b\x08\x00", "application/octet-stream", "c.zip")
    assert not ok, "扩展名是 .zip 但首字节不是 ZIP —— 多半是镜像的 gzip 错误页"
    assert "zip" in why.lower() or ".zip" in why


def test_json_asset_is_not_treated_as_binary() -> None:
    """Manifest.json 这类文本资产必须放行（否则会把正常的 JSON 当假包）。"""
    assert fastnet.validate_payload(b'{"files": []}', "application/json", "Manifest.json")[0]


# ---------------------------------------------------------------- 早判发生在"开始下载"之前
def test_attempt_line_rejects_bad_payload_before_downloading(monkeypatch) -> None:
    """关键：**不能先下再校验**。探测到网页就立刻抛，别去调下载器。"""
    monkeypatch.setattr(
        fastnet, "probe",
        lambda url, timeout=30: (12345, True, url, b"<!DOCTYPE html>", "text/html"))
    called = {"download": 0}

    def _boom(*args, **kwargs):
        called["download"] += 1
        raise AssertionError("假包不该走到下载器")

    monkeypatch.setattr(fastnet, "_download_sequential", _boom)
    with pytest.raises(OSError) as excinfo:
        fastnet._attempt_line("https://mirror.example/pkg.zip", fastnet.Path("x.zip"),
                              line=fastnet.DIRECT)
    assert called["download"] == 0, "必须在下任何字节之前判死"
    assert "网页" in str(excinfo.value) or "HTML" in str(excinfo.value)


# ---------------------------------------------------------------- 内置镜像表（2026-11-07 实测）
def test_default_lines_use_measured_fastest_mirror() -> None:
    """本次实测 gh.monlor.com 0.49 MB/s 最快 ⇒ 它必须排在第一（直连之后）。"""
    names = [line.name for line in fastnet.DEFAULT_LINES]
    assert names[0] == "直连"
    assert names[1] == "gh.monlor.com", f"实测最快的镜像应排第一，当前顺序 {names}"
    for keep in ("ghproxy.net", "gh.nxnow.top", "gh-proxy.com"):
        assert keep in names, f"实测能用的 {keep} 不该被删掉"


def test_default_lines_exclude_known_dead_or_fake_mirrors() -> None:
    """返回网页 / 证书不符 / 域名没了 的一律不进默认表（只会白占一次尝试）。"""
    names = {line.name for line in fastnet.DEFAULT_LINES}
    for bad in ("ghps.cc", "ghproxy.cfd", "ghproxy.link", "gh-proxy.net", "gh.tryxd.cn",
                "ghproxy.cc", "cf.ghproxy.cc", "ghfast.top", "gh.ddllc.top", "gh.ddlc.top",
                "github.moeyy.xyz", "gh.llkk.cc", "hub.gitmirror.com"):
        assert bad not in names, f"{bad} 本次实测不可用，不该留在默认表里"


# ---------------------------------------------------------------- 日志不再自相矛盾
def test_pool_log_does_not_claim_direct_is_excluded_from_attempts() -> None:
    src = (fastnet.__file__ or "")
    text = open(src, encoding="utf-8").read()
    assert "备用镜像抢块池" in text, "抢块池的措辞要说清「池子里是谁」，别写成「已启用」"
    assert "多线路动态抢块已启用" not in text, (
        "旧措辞会和紧接着的「尝试线路：直连」自相矛盾 —— 用户实测就是被它绕晕的"
    )


def test_slow_line_thread_count_is_logged_once() -> None:
    src = (fastnet.__file__ or "")
    text = open(src, encoding="utf-8").read()
    assert "仍用 {threads} 连接试" not in text, (
        "慢线路那段曾在最终决定前先报一次线程数（12），随后实际用的是 8 —— 只许报最终值"
    )
