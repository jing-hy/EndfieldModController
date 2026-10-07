"""Endfield Poser 集成的离线单测。

**不触网、不下载、不碰真实游戏目录**：全部在 tmp_path 里造假的游戏目录 / 安装包，
并用 monkeypatch 把 `game_dir` / `pack_root` / `runtime_path` 指过去。

覆盖的点（都是 2026-10-01 落地时定下的行为）：
* 状态识别：装好了 / 只被开关停用 / 被净化后的"记录在、dll 不在"中间态；
* loader 归属：Poser 的 proxy 标记必须被认出来（此前只认乳摇那套 → 漏判）；
* 开关：重命名实现，来回可逆；
* 乳摇卸载保护：plugin 里还有 Poser 时**不许**把 proxy 还原成系统原版；
* 净化：Poser 的安装记录 / 姿态库 / 表情校准要被收进 poser_data 并可从备份还原；
* 安装向导调用：参数与"无黑窗"标志；
* 安装包下载：必须走 release 列表接口（上游只发预发布版），且只挑 win64.zip。
"""
from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from endfieldmodcontroller import game_clean, poser, reshade_integration, runtime_deps, secondary_motion
from endfieldmodcontroller.config import AppConfig

POSER_PROXY = b"MZ" + b"\x00" * 128 + b"[PROXY] plugins loaded via Endfield Poser proxy"
SBM_PROXY = b"MZ" + b"\x00" * 128 + b"[LOADER] started, base=%s"
SYSTEM_DLL = b"MZ" + b"\x00" * 2_000_000          # 系统原版：几 MB，不是 proxy
FAKE_POSER_DLL = b"MZ" + b"poser-dll-body" * 64


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _record(files: list[dict]) -> dict:
    return {"product": "Endfield Poser", "schema": 1, "files": files,
            "installed_at": "2026-10-01T00:00:00.0000000+08:00"}


def _installed_record(game: Path) -> dict:
    import hashlib

    dll = game / "plugin" / "poser.dll"
    # dll 不存在时（"净化之后的中间态"用例）用占位哈希，别在这里就炸
    digest = hashlib.sha256(dll.read_bytes()).hexdigest() if dll.is_file() else "0" * 64
    return _record([
        {"path": "plugin\\poser.dll", "installed_sha256": digest,
         "original": None, "original_sha256": None},
        {"path": "d3dcompiler_47.dll", "installed_sha256": "0" * 64,
         "original": None, "original_sha256": None},
    ])


def _fake_pack(root: Path) -> Path:
    """假安装包：只放向导脚本（内容无所谓，测试里不会真的执行 powershell）。"""
    _write(root / "tools" / "deploy.ps1", b"# fake deploy\n")
    _write(root / "plugin" / "poser.dll", FAKE_POSER_DLL)
    _write(root / "plugin" / "d3dcompiler_47.dll", POSER_PROXY)
    _write(root / "plugin" / "vulkan-1.dll", POSER_PROXY)   # 真实包里两个 loader proxy 都有
    return root


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """假游戏目录 + 假安装包 + 假 config（三个路径都指到 tmp_path）。"""
    game = tmp_path / "Endfield Game"
    (game / "plugin").mkdir(parents=True, exist_ok=True)
    _write(game / "Endfield.exe", b"MZ")
    pack = _fake_pack(tmp_path / "poser")
    config = AppConfig()
    monkeypatch.setattr(AppConfig, "poser_path", property(lambda self: pack))
    monkeypatch.setattr(AppConfig, "runtime_path", property(lambda self: tmp_path / "runtime"))
    monkeypatch.setattr(poser, "game_dir", lambda cfg: game)
    monkeypatch.setattr(secondary_motion, "game_dir", lambda cfg: game)
    monkeypatch.setattr(poser, "_game_running", lambda: 0)
    monkeypatch.setattr(reshade_integration, "detect_game_dir", lambda cfg, **kw: game)
    return SimpleNamespace(tmp=tmp_path, game=game, pack=pack, config=config)


# --------------------------------------------------------------- loader 识别（回归）
def test_loader_kind_recognizes_both_flavours(env):
    poser_proxy = _write(env.tmp / "poser_proxy.dll", POSER_PROXY)
    sbm_proxy = _write(env.tmp / "sbm_proxy.dll", SBM_PROXY)
    system = _write(env.tmp / "system.dll", SYSTEM_DLL)

    assert reshade_integration.loader_kind(poser_proxy) == "poser"
    assert reshade_integration.loader_kind(sbm_proxy) == "sbm"
    assert reshade_integration.loader_kind(system) == ""
    # 关键回归：Poser 的 proxy 也必须被判成 loader proxy（否则审计/净化/停用全漏判）
    assert reshade_integration.looks_like_loader_proxy(poser_proxy) is True
    assert reshade_integration.looks_like_loader_proxy(sbm_proxy) is True
    assert reshade_integration.looks_like_loader_proxy(system) is False


# --------------------------------------------------------------- 状态
def test_status_installed_with_poser_loader(env):
    _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)
    _write(env.game / "d3dcompiler_47.dll", POSER_PROXY)
    _write(env.game / "plugin" / "poser-install.json",
           json.dumps(_installed_record(env.game)).encode("utf-8"))
    _write(env.game / "plugin" / "mmd" / "character-faces" / "aglina-9fb0b6c4fbb6.face.json", b"{}")
    _write(env.game / "plugin" / "poses" / "pose-a.poser.json", b"{}")
    _write(env.game / "plugin" / "poser_log.txt", b"line1\nline2\n")

    state = poser.status(env.config, include_web=False)
    assert state["pack_ready"] is True
    assert state["installed"] is True and state["enabled"] is True and state["parked"] is False
    assert state["loader_kind"] == "poser"
    assert state["proxy_owned"] is True
    assert state["record_consistent"] is True
    assert state["face_count"] == 1 and state["pose_count"] == 1
    assert state["log_tail"][-1] == "line2"
    assert poser._needs_install(state) == (False, "")


def test_install_record_with_bom_is_recognised(env):
    """上游写的安装记录**带 UTF-8 BOM**，必须照读（2026-10-02 反馈者诊断包定位）。

    `tools\\deploy.ps1` 用 PowerShell 5.1 的 `Set-Content … -Encoding UTF8` 写这份记录，
    它会写 BOM；以前按 `utf-8` 读 → `json.loads` 抛 `Unexpected UTF-8 BOM` → 被吞成 `{}`
    → 判「缺少安装记录 plugin\\poser-install.json」→ **每点一次「修复」都重跑一遍 Poser
    安装向导**，界面停在「修复后仍有缺失」（向导每次都回"无需替换"，所以永远修不好）。
    """
    _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)
    _write(env.game / "d3dcompiler_47.dll", POSER_PROXY)
    _write(env.game / "plugin" / "mmd" / "character-faces" / "aglina-9fb0b6c4fbb6.face.json", b"{}")
    record = json.dumps(_installed_record(env.game)).encode("utf-8")
    _write(env.game / "plugin" / "poser-install.json", b"\xef\xbb\xbf" + record)   # 带 BOM

    state = poser.status(env.config, include_web=False)
    assert state["record"] is True, "带 BOM 的记录必须被认出来（否则每次修复都会重装一遍 Poser）"
    assert state["record_consistent"] is True
    assert poser._needs_install(state) == (False, "")


def test_status_middle_state_after_clean(env):
    """净化之后：安装记录还在，但 dll 与 proxy 已被移走 → 必须判成"需要重装"。"""
    _write(env.game / "plugin" / "poser-install.json",
           json.dumps(_installed_record(env.game)).encode("utf-8"))
    state = poser.status(env.config, include_web=False)
    assert state["installed"] is False
    assert state["record"] is True
    needs, reason = poser._needs_install(state)
    assert needs is True and "poser.dll" in reason


def test_status_parked_is_not_missing(env):
    """被开关停用（改名）时不算缺文件 —— 不该因此去跑安装向导。"""
    _write(env.game / "plugin" / ("poser.dll" + poser.PARKED_SUFFIX), FAKE_POSER_DLL)
    state = poser.status(env.config, include_web=False)
    assert state["installed"] is False and state["parked"] is True
    assert poser._needs_install(state) == (False, "")


# --------------------------------------------------------------- 开关
def test_set_enabled_roundtrip(env):
    target = _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)
    parked = env.game / "plugin" / ("poser.dll" + poser.PARKED_SUFFIX)

    off = poser.set_enabled(env.config, False)
    assert off["ok"] is True and off["changed"] is True
    assert not target.is_file() and parked.is_file()

    # 再点一次关：幂等
    off_again = poser.set_enabled(env.config, False)
    assert off_again["ok"] is True and off_again["changed"] is False

    on = poser.set_enabled(env.config, True)
    assert on["ok"] is True and on["changed"] is True
    assert target.is_file() and not parked.is_file()
    assert target.read_bytes() == FAKE_POSER_DLL


def test_set_enabled_without_install_is_readable(env):
    result = poser.set_enabled(env.config, True)
    assert result["ok"] is False and "还没装" in result["message"]


# --------------------------------------------------------------- 乳摇卸载保护
def test_sbm_uninstall_keeps_loader_for_other_plugins(env):
    _write(env.game / "d3dcompiler_47.dll", SBM_PROXY)
    _write(env.game / "d3dcompiler_47.dll.bak", SYSTEM_DLL)
    _write(env.game / "plugin" / "sbm.dll", b"MZ" + b"sbm" * 32)
    _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)

    result = secondary_motion.remove_injection(env.config)
    assert result["ok"] is True
    proxy = env.game / "d3dcompiler_47.dll"
    assert proxy.is_file(), "plugin 里还有别的插件时必须保留 loader"
    assert proxy.read_bytes() == SBM_PROXY, "不能把 proxy 换成系统原版"
    assert not (env.game / "plugin" / "sbm.dll").is_file(), "sbm 自己的 dll 仍要卸掉"
    assert (env.game / "plugin" / "poser.dll").is_file(), "不能动别人的插件"
    assert any("保留 loader" in action for action in result["actions"])


def test_sbm_uninstall_restores_when_alone(env):
    _write(env.game / "d3dcompiler_47.dll", SBM_PROXY)
    _write(env.game / "d3dcompiler_47.dll.bak", SYSTEM_DLL)
    _write(env.game / "plugin" / "sbm.dll", b"MZ" + b"sbm" * 32)

    result = secondary_motion.remove_injection(env.config)
    assert result["ok"] is True
    assert (env.game / "d3dcompiler_47.dll").read_bytes() == SYSTEM_DLL


# --------------------------------------------------------------- 净化 / 还原
def test_game_clean_audits_and_restores_poser_data(env):
    _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)
    _write(env.game / "d3dcompiler_47.dll", POSER_PROXY)
    _write(env.game / "plugin" / "poser-install.json",
           json.dumps(_installed_record(env.game)).encode("utf-8"))
    _write(env.game / "plugin" / "poses" / "a.poser.json", b"{}")
    _write(env.game / "plugin" / "mmd" / "character-faces" / "x-0123456789ab.face.json", b"{}")

    report = game_clean.audit(env.config)
    categories = {item["category"] for item in report["findings"]}
    relatives = {item["relative"] for item in report["findings"]}
    assert "poser_data" in categories
    assert "plugin/poser-install.json" in relatives
    assert "plugin/poses" in relatives
    assert "plugin/mmd" in relatives

    result = game_clean.backup_and_clean(env.config)
    assert result["backup_dir"], result.get("errors")
    assert not (env.game / "plugin" / "poser-install.json").is_file()
    assert not (env.game / "plugin" / "poses").exists()

    restored = game_clean.restore(env.config)
    assert restored["ok"] is True, restored.get("errors")
    assert (env.game / "plugin" / "poser-install.json").is_file()
    assert (env.game / "plugin" / "poses" / "a.poser.json").is_file()


# --------------------------------------------------------------- 安装向导调用
def test_wizard_uses_upstream_script_without_console(env, monkeypatch):
    calls: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        return subprocess.CompletedProcess(command, 0, stdout=b"[PROXY] ok", stderr=b"")

    monkeypatch.setattr(poser.subprocess, "run", fake_run)
    result = poser._run_wizard(env.config, "Install")
    assert result["ok"] is True
    command, kwargs = calls[0]
    assert command[0] == "powershell.exe"
    assert str(env.pack / "tools" / "deploy.ps1") in command
    assert "-GameDir" in command and str(env.game) in command
    assert "-Action" in command and "Install" in command
    assert "-SourceRoot" in command and str(env.pack) in command
    assert kwargs.get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert "shell" not in kwargs


def test_wizard_failure_is_readable(env, monkeypatch):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr="游戏仍在运行".encode("utf-8"))

    monkeypatch.setattr(poser.subprocess, "run", fake_run)
    result = poser._run_wizard(env.config, "Install")
    assert result["ok"] is False
    assert "安全安装.bat" in result["message"]


def test_remove_injection_restores_parked_copy_first(env, monkeypatch):
    """被开关停用过（改过名）的文件，卸载前必须先改回原名，否则向导找不到它。"""
    _write(env.game / "plugin" / ("poser.dll" + poser.PARKED_SUFFIX), FAKE_POSER_DLL)
    seen: list[str] = []

    def fake_wizard(config, action, log=None):
        seen.append(action)
        # 向导"真的"删掉了文件
        (env.game / "plugin" / "poser.dll").unlink(missing_ok=True)
        return {"ok": True, "message": "ok"}

    monkeypatch.setattr(poser, "_run_wizard", fake_wizard)
    result = poser.remove_injection(env.config)
    assert seen == ["Uninstall"]
    assert result["ok"] is True
    assert not (env.game / "plugin" / ("poser.dll" + poser.PARKED_SUFFIX)).is_file()


# --------------------------------------------------------------- 安装包下载
def test_ensure_poser_uses_release_list_and_win64_asset(env, monkeypatch):
    captured: dict = {}

    def fake_releases_list(repo, **kwargs):
        captured["repo"] = repo
        captured["kwargs"] = kwargs
        return {
            "tag_name": "v0.4.92", "prerelease": True, "assets": [
                {"name": "Endfield-Poser-v0.4.92-source.zip", "size": 1, "browser_download_url": "u-source"},
                {"name": "Endfield-Poser-v0.4.92-win64.zip", "size": 2, "browser_download_url": "u-win64"},
                {"name": "SHA256SUMS.txt", "size": 3, "browser_download_url": "u-sums"},
            ],
        }

    def fake_download_extract(url, asset_name, target, *args, **kwargs):
        captured["url"] = url
        captured["asset"] = asset_name
        _write(Path(target) / "plugin" / "poser.dll", FAKE_POSER_DLL)

    from endfieldmodcontroller import github

    monkeypatch.setattr(github, "releases_list", fake_releases_list)
    monkeypatch.setattr(runtime_deps, "_download_extract", fake_download_extract)

    # ⚠️ 必须 `force=True`：2026-10-03 起「自动更新依赖关着 + 本地已就位 ⇒ 不联网」
    # 是启动流程的既定行为（用户实测"一键启动 62 秒"就是被这个坑的），
    # 这条测试验的是**下载链路**（预发布版 + win64 资产），所以走显式更新那条路。
    result = runtime_deps.ensure_poser(env.config, force=True)
    assert result.status == "installed"
    assert captured["repo"] == "OedoSoldier/Endfield-Poser"
    assert captured["kwargs"].get("include_prerelease") is True
    assert captured["asset"] == "Endfield-Poser-v0.4.92-win64.zip"
    assert captured["url"] == "u-win64"
    assert poser._pack_version(env.pack) == "v0.4.92"


def test_import_pack_rejects_foreign_zip(env, tmp_path):
    archive = tmp_path / "not-poser.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("readme.txt", "hello")
    result = poser.import_pack(env.config, archive)
    assert result["ok"] is False and "poser.dll" in result["message"]


# --------------------------------------------------------------- 只读摆姿页
def test_web_status_degrades_quietly(env, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(poser.urllib.request, "urlopen", boom)
    info = poser.web_status()
    assert info["reachable"] is False and info["reason"]


# --------------------------------------------------------------- loader 自补（2026-10-03 用户实测）
def test_ensure_loader_replaces_system_copy_and_keeps_backup(env):
    """游戏目录里是**系统原版**（几 MB）时：备份原版 → 放我们包里的 proxy。"""
    system = _write(env.game / "d3dcompiler_47.dll", SYSTEM_DLL)
    assert reshade_integration.looks_like_loader_proxy(system) is False

    result = poser.ensure_loader(env.config)

    assert result["ok"], result
    target = env.game / "d3dcompiler_47.dll"
    assert reshade_integration.looks_like_loader_proxy(target) is True, "proxy 必须被放进去"
    backup = env.game / "d3dcompiler_47.dll.bak"
    assert backup.is_file() and backup.stat().st_size == SYSTEM_DLL.__len__(), "原版要留备份"
    assert any("部署 loader d3dcompiler_47.dll" in a for a in result["actions"])


def test_ensure_loader_is_a_noop_when_proxy_already_there(env):
    _write(env.game / "d3dcompiler_47.dll", POSER_PROXY)

    result = poser.ensure_loader(env.config)

    assert result["actions"] == [], f"已经有 loader 就别再动它：{result}"


def test_reopen_uses_our_loader_instead_of_the_upstream_wizard(env, monkeypatch):
    """★ 核心回归：**只缺 loader** 时不许去跑上游向导。

    用户实测（2026-10-03）：向导看到游戏目录里那个系统原版的 `d3dcompiler_47.dll`，
    判定「文件已被其他程序替换，无法确认为本插件」直接 exit 1 ⇒ 开关永远打不开。
    现在这条路由我们自己的 `ensure_loader` 兜住。
    """
    _write(env.game / "d3dcompiler_47.dll", SYSTEM_DLL)
    _write(env.game / "plugin" / "poser.dll", FAKE_POSER_DLL)
    _write(env.game / "plugin" / "poser-install.json", b"{}")   # 有记录

    def fake_status(cfg, **kw):
        # 真实反映"loader 在不在"：补之前为空、补完就是 poser ⇒ 第二次不该再要向导
        return {
            "installed": True, "parked": False, "record": True, "record_consistent": None,
            "loader_kind": ("poser" if reshade_integration.looks_like_loader_proxy(
                env.game / "d3dcompiler_47.dll") else ""),
            "face_count": 37, "pack_ready": True,
        }

    monkeypatch.setattr(poser, "status", fake_status)

    def _no_wizard(*args, **kwargs):  # pragma: no cover
        raise AssertionError("只缺 loader 时不该跑上游向导")

    monkeypatch.setattr(poser, "_run_wizard", _no_wizard)

    result = poser.ensure_injection(env.config)

    assert result["ok"] is True, result
    assert any("部署 loader" in a for a in result["actions"]), result["actions"]


def test_other_plugins_sees_disabled_poser(env):
    """关乳摇时不能把 Poser 的底座拆掉 —— 停用中的 Poser（`.disabled`）也算"还在"。"""
    _write(env.game / "plugin" / "poser.dll.endfieldmodcontroller.disabled", FAKE_POSER_DLL)
    assert secondary_motion._other_plugin_dlls(env.game) == ["poser.dll"], \
        "停用副本必须被认出来，否则卸载乳摇会把 loader 一起还原"


# ---------------------------------------------------------------------------
# ⑧ get_state 不得做网络 IO（2026-10-07 实测定位）
# ---------------------------------------------------------------------------


def test_get_state_does_not_probe_poser_web_ui():
    """★ 回归（2026-10-07）：`get_state` 跑在 GUI 线程上，**绝不能探测 Poser 的 Web UI**。

    实测（cProfile）：Poser 的本地 HTTP 探测（`127.0.0.1:18923`）在 Poser 没运行时**不是
    立刻被拒、而是等满超时** ⇒ `get_state` 每次 1.6 秒里 **1.515 秒全花在 socket.connect**；
    而前端启动阶段密集调它（实测 1 秒内 5 次）⇒ 整个界面都发滞。改掉之后 1.98s → 0.07s。

    为什么不写成行为测试：`get_state` 依赖整台机器的现场（tmp 环境下会在走到 poser 之前
    就先抛异常，那条路测不到）。这里直接钉**那一行调用**的参数 —— 参数一退化就变红。
    """
    import inspect

    from endfieldmodcontroller import api as api_mod

    source = inspect.getsource(api_mod.EndfieldModControllerApi.get_state)
    calls = [line for line in source.splitlines() if "poser.status(" in line]
    assert calls, "get_state 里应当调用 poser.status"
    assert all("include_web=False" in line for line in calls), \
        f"get_state 里的 poser.status 必须带 include_web=False：{calls}"


def test_poser_web_timeout_is_short():
    """本地回环探测的超时必须短 —— 1.5 秒那种取值会把 GUI 线程拖住。"""
    from endfieldmodcontroller import poser

    assert poser.WEB_TIMEOUT <= 0.5, poser.WEB_TIMEOUT