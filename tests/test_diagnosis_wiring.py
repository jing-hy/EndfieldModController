"""诊断接线与判据有效性的回归测试（2026-10-06）。

这些都来自**反馈者 1.0.15 那份包**里暴露的"判据看着有、其实等于没生效"：

1. 注入时间线里的**签名长度恒为 0** —— `dlss5_injection_status()` 的返回**根本没有签名字段**
   （而 summary 另一段自己读 json 却读出 `140`，同一份文件两个结论）；
2. 运行时采样里的 **ReShade 行数恒为 0** —— 采样读的是 `runtime\\dlss5\\ReShade.log`
   （部署源目录，通常没有这个文件），而 ReShade 按 `RESHADE_BASE_PATH_OVERRIDE`
   把日志写在 `runtime\\reshade\\`；
3. 「注入现场时间线」段**写了函数没接进 summary 链** ⇒ 包里有 jsonl、summary 里却没有；
4. Streamline / NGX 的清单**一个都不收**，而 `Player.log` 指出 `parseServerManifest`
   读到乱码（`ota.cpp:329`，连报 10 次）⇒ 按用户定的规矩「要看没被收的，先把收包范围改掉」。

**要守住的性质**：接线必须在源码里成立（判据只有一处）、路径必须指向**生效那份**、
时间线必须真的把「该进进程的两条在不在」渲染出来。
"""
from __future__ import annotations

import inspect

from endfieldmodcontroller import crashwatch, diagnostics, injecttrace, launcher


def test_injection_status_exposes_signature_lengths():
    """★ 注入状态必须带出签名（否则时间线上那条判据永远是 0）。"""
    src = inspect.getsource(launcher.dlss5_injection_status)
    # ⚠️ 判据必须**精确到赋值语句**：这条函数的**注释里**也提到了
    #    `extra_libraries_signature`（解释为什么要把签名带出来），
    #    只查"这个词有没有出现"会假绿 —— 反向验证 Q 就是这么把它抓出来的。
    assert 'status["extra_libraries_signature"]' in src, "没有把签名带出来 ⇒ injecttrace 读不到"
    assert 'status["user_signature"]' in src


def test_injecttrace_reads_the_signature_field_it_exists():
    """`injecttrace` 取的字段名必须与 `dlss5_injection_status` 提供的一致。"""
    status_src = inspect.getsource(launcher.dlss5_injection_status)
    trace_src = inspect.getsource(injecttrace._injection_state)
    assert 'status.get("extra_libraries_signature")' in trace_src
    assert 'status["extra_libraries_signature"]' in status_src


def test_trace_summary_is_wired_into_summary_chain():
    """★ 时间线段必须真的接进 summary 链（否则包里有 jsonl、summary 里没有）。"""
    src = inspect.getsource(diagnostics)
    assert "def _injection_trace_summary" in src
    assert "summary.extend(_injection_trace_summary(config))" in src, "没接进 summary 链"
    body = inspect.getsource(diagnostics._injection_trace_summary)
    assert "expect_missing" in body, "没有渲染「该进进程的两条在不在」"
    assert "phase_label" in body
    assert "extra_libraries" in body, "没有逐条列出注入库"


def test_trace_summary_renders_entries_and_handles_empty(monkeypatch):
    """渲染要能吃真条目，也要能对空/异常给出可读结论。"""
    monkeypatch.setattr(injecttrace, "read_all", lambda config: [{
        "at": "02:53:44", "phase": "game-started", "phase_label": "终末地启动后", "note": "",
        "injection": {"enabled": True, "signature_len": 140,
                      "extra_libraries": ["X:/dlss5/d3d12.dll", "X:/EFMI/d3d11.dll"]},
        "process": {"pid": 123, "module_count": 52, "third_party_count": 9,
                    "expect_missing": ["d3d11.dll"]},
        "game_injections": ["plugin/sbm.dll"],
    }])
    text = "\n".join(diagnostics._injection_trace_summary(object()))
    assert "终末地启动后" in text
    assert "X:/dlss5/d3d12.dll" in text
    assert "签名长度=140" in text
    assert "缺 d3d11.dll" in text, "该进却没进的必须在包里点名"
    monkeypatch.setattr(injecttrace, "read_all", lambda config: [])
    empty = "\n".join(diagnostics._injection_trace_summary(object()))
    assert "没有记录" in empty


def test_sample_reads_the_effective_reshade_log():
    """★ 采样必须读**生效那份** ReShade.log（否则 ReShade 行数恒为 0）。"""
    src = inspect.getsource(crashwatch)
    assert "nr_autostart.reshade_log_path(config)" in src, "没有用生效那份的路径"
    assert 'reshade_log=Path(config.dlss5_path) / "ReShade.log"' not in src, "旧路径还在"


def test_collector_covers_streamline_and_ngx_manifests():
    """★ 收包范围必须覆盖 Streamline / NGX 的清单（那里才是 parseServerManifest 读的东西）。"""
    src = inspect.getsource(crashwatch.collect_diagnosis_files)
    assert "Streamline" in src
    assert "NGX" in src
    assert "nvidia-" in src, "收进来的文件要有可辨认的前缀"
    assert "512 * 1024" in src, "大文件要按节选原则跳过"
    assert "game-" in src, "游戏目录下的小清单也要收"
