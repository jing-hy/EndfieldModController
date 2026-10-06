"""自更新现场必须进诊断包（2026-10-06）。

起因：反馈者（`F:\\EndfieldModController`）原话「**自更新下载完就没了，没提示重启，
手动按重启也没用**」—— 日志里只有一句 `自更新已下载：v1.0.19 已下载完成`，
之后反复 `清理上次更新残留: EndfieldModController.exe.old`；
而当时的包里**一条相关证据都没有**：看不到已下载的载荷还在不在、有没有 `.old`/`.new`/
`update-failed.txt`，更看不到**当前这个 exe 自己的大小与 sha256**
（那是"他现在跑的是哪一版"的**唯一直接判据**）。
"""
from __future__ import annotations

from endfieldmodcontroller import crashwatch, runtime_assets, selfupdate
from endfieldmodcontroller.config import AppConfig


def _env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    runtime = root / "runtime"
    for sub in ("dlss5", "reshade", "logs", "builtin", "_update"):
        (runtime / sub).mkdir(parents=True, exist_ok=True)
    config = AppConfig(runtime_dir=str(runtime), library_dir=str(root / "library"),
                       dlss5_dir=str(runtime / "dlss5"),
                       builtin_runtime_dir=str(runtime / "builtin"))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: runtime))
    monkeypatch.setattr(AppConfig, "dlss5_path", property(lambda self: runtime / "dlss5"))
    monkeypatch.setattr(AppConfig, "reshade_runtime_path",
                        property(lambda self: runtime / "reshade"))
    monkeypatch.setattr(AppConfig, "staging_mods_path",
                        property(lambda self: runtime / "builtin" / "XXMI" / "EFMI" / "Mods"))
    monkeypatch.setattr(AppConfig, "xxmi_launcher_path", property(lambda self: None))
    monkeypatch.setattr(runtime_assets, "manifest_entries", lambda config: [])
    monkeypatch.setattr(crashwatch, "_collect_injection_files", lambda config, dest: None)
    return config, tmp_path, runtime


def test_self_update_forensics_is_collected(tmp_path, monkeypatch):
    """★ 包里要能看到：当前 exe 指纹、`.old` 残留、`_update` 载荷清单、待安装判定。"""
    config, tmp_path, runtime = _env(tmp_path, monkeypatch)
    # 假装"当前正在跑的程序"就是某个 exe，旁边有上次替换没清掉的 .old
    fake_exe = tmp_path / "EndfieldModController.exe"
    fake_exe.write_bytes(b"exe-body")
    (tmp_path / "EndfieldModController.exe.old").write_bytes(b"old-body")
    (runtime / "_update" / "EndfieldModController.exe").write_bytes(b"payload")
    (runtime / "_update" / "last_check.json").write_text('{"latest": "9.9.9"}', encoding="utf-8")
    monkeypatch.setattr(selfupdate, "executable_path", lambda: fake_exe)

    dest = tmp_path / "out"
    notes: list[str] = []
    taken = crashwatch.collect_diagnosis_files(config, dest, log=notes.append)

    assert "self-update-forensics.txt" in taken, (taken, notes)
    text = (dest / "self-update-forensics.txt").read_text(encoding="utf-8")
    assert str(fake_exe) in text
    assert "sha256=" in text, "必须带上当前 exe 的 sha256（判'跑的是哪一版'的唯一直接证据）"
    assert "EndfieldModController.exe.old" in text, "替换残留是判断'换没换成功'的关键"
    assert "EndfieldModController.exe" in text and "_update" in text, "载荷清单"
    assert "待安装判定" in text


def test_apply_update_failures_are_logged(monkeypatch, tmp_path):
    """★ `apply_update` 的**每条**失败都要落日志（否则用户点重启没反应时无从查起）。"""
    config, _tmp_path, _runtime = _env(tmp_path, monkeypatch)
    lines: list[str] = []
    monkeypatch.setattr(selfupdate, "is_frozen", lambda: False)

    result = selfupdate.apply_update(config, log=lines.append)

    assert result["ok"] is False
    assert lines and "替换未执行" in lines[0], lines
