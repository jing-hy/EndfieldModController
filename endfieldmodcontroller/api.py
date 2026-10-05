"""Backend API exposed to the PyWebview frontend."""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from . import activation, core, dependencies, diagnostics, dlss5_fetcher, fsutil, hot_reload, integrity, launcher, moddl, reshade, reshade_integration, runtime_assets, runtime_deps, selfupdate
from .config import AppConfig, auto_detect_migoto_loader, auto_detect_official_launcher, auto_detect_xxmi, cached_detect

# 拖进 Mod 库页面的压缩包格式（用户 2026-10-01：「需要增加支持拖入 7z」「rar 也要」）。
# zip 走标准库（自带 zip-slip 防护），7z/rar 走外部解压器（见 dependencies.find_archive_tool）。
IMPORT_SUFFIXES = (".zip", ".7z", ".rar")

# ── 导入压缩包的大小上限（2026-10-03 用户选 A：**直接去掉原来那个 600 MB**）──────
# 用户报：「**mod 超过 600mb 就显示请手动解压放入，但是动态还一直卡在那里，
# 为什么定额这么低**」。两件事分别处理：
#   ① **600 MB 本身过时**：它来自更早"一次性 base64 传整包"的时代（那条路在
#      `import_mod_archive`，限额 300 MB，注释写着"避免超大包把内存和调用参数撑爆"）。
#      而**分块上传是流式 `open(..., "ab")` 直接写磁盘的**、全程不把整包读进内存
#      ⇒ 没有技术上必须卡在 600 MB 的理由。**用户明确选了 A（直接去掉限额）**。
#   ② **"卡住"的根因是超限时的写法**：原实现只 `return {"ok": False}`，**不删**已写进
#      磁盘的 `.part`、**不清理** `_import_sessions` 会话、**不更新**任务状态 ⇒
#      进度停在超限那一刻、临时文件留在 `runtime\_incoming\`。
#
# 现在：**不再按大小拒绝**（交给磁盘空间），只留一个**防呆**上限 ——
# 挡住"误拖一个几十 GB 的包把磁盘塞满"这种自伤；一旦触发就彻底清理并如实说明。
# 8 GB：正常 Mod（含那个 912 MB 的）都在它之下，而它又远小于"误拖整个盘"的量级。
IMPORT_HARD_CAP_BYTES = 8 * 1024 ** 3


def _keep_failed_import(config: Any, archive: Path, name: str = "") -> Path:
    r"""把导入失败的包**搬到用户能找到的地方**并返回它的新路径。

    ⚠️ **为什么必须搬**（2026-10-03 用户：「**而且它显示的文件地址也显示找不到**」）：
    拖入时包先落在 `runtime\\_incoming\\<token>.zip`，而 `import_mod_finish()` 与
    `import_mod_archive()` 的 `finally` **不管成功失败都会删掉它** ⇒ 我在弹窗里给出的
    `source_path` **在显示出来的时候就已经不存在了**，用户点"打开文件夹"只会看到"找不到"。

    现在失败时**不删**，搬进 `<数据根>\runtime\需手动解压\`（固定、可见、不会被自动清理），
    返回搬过去之后的路径 —— 那个路径**真的存在**，用户可以自己去解压。
    搬不动（磁盘满 / 权限）就退回原路径并保持文件不动，**绝不因为搬不动就把包弄丢**。
    """
    archive = Path(archive)
    try:
        dest_dir = Path(config.runtime_path) / "需手动解压"
        dest_dir.mkdir(parents=True, exist_ok=True)
        # ⚠️ **用用户认识的原始文件名**（`name`），而不是内部的 `<token>.zip`。
        # 拖入时落盘名是 `<时间戳>-<pid>-<hash>.zip`，直接搬过去用户根本不知道那是啥
        #（实测：提示里出现 `1791028589-39772-59503.zip`，毫无意义）。
        wanted = Path(str(name or "")).name or archive.name
        target = dest_dir / wanted
        counter = 1
        while target.exists():
            counter += 1
            target = dest_dir / f"{Path(wanted).stem}_{counter}{Path(wanted).suffix}"
        archive.replace(target)          # 同盘 move；跨盘会退化成 copy+unlink
        return target
    except OSError:
        return archive


def _manual_extract_hint(reason: str, archive: Path, library: Path) -> str:
    """把一条解压错误变成**用户可以照做的指引**（含文件地址与目标地址）。

    用户 2026-10-03 原话：「**解压失败弹窗应该给出文件地址和目标地址，让用户自行解压
    放进去，下载的解压也是**」。所以这里统一产出：原因 + 压缩包在哪 + 应该解压到哪 +
    一条可以直接复制的命令（用 Windows 自带 tar，不必先装 7-Zip）。
    """
    archive = Path(archive)
    library = Path(library)
    stem = archive.stem
    lines = [
        str(reason or "解压失败").strip(),
        "",
        "**压缩包**（已帮你留好，没有删除）：",
        f"  {archive}",
        "",
        "**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：",
        f"  {library}",
        "",
        f"手动做法：把上面那个包解压，得到 `{stem}` 文件夹（如果解压出来是好几层，"
        f"只保留最外层那一层就行），整个文件夹放进 Mod 库，再回界面点「重新扫描」。",
        "",
        "如果手边没有解压软件，Windows 自带的 tar 就能解（在 PowerShell 里跑）：",
        f'  tar -xf "{archive}" -C "{library}"',
    ]
    return "\n".join(lines)
IMPORT_SUFFIX_HINT = " / ".join(IMPORT_SUFFIXES)


def _tree_digest(root: Path) -> str:
    """算一个目录的内容指纹（相对路径 + 每个文件内容的 sha256），用于**判重复**。

    只比"文件名 + 内容"，与大小写/时间戳无关。用户 2026-10-03 反馈「去重没做好，
    现在莱万汀那里有两个一样的」——那两份 82 个文件的指纹逐一相同。
    """
    import hashlib

    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        try:
            with open(path, "rb") as handle:
                while True:
                    block = handle.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(hashlib.sha256(block).digest())
        except OSError:
            # 读不到的文件（被占用/权限）不该让判重崩掉，用路径占位并继续
            digest.update(b"<unreadable>")
        digest.update(b"\0")
    return digest.hexdigest()


class EndfieldModControllerApi:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config = AppConfig.load(config_path)
        # ⚠️ **配置热重载**（2026-10-03 用户要求：「我没在运行管理器，实例读的不是应该随着修改
        # 实时更新吗，**改一下就读一次**」）。
        # 原来 `self.config` 是启动时 load 一次、之后一直用内存那份 —— 于是"改了设置不重启
        # 就不生效"（实测：他把 `mod_backup_dir` 改成 `D:\zmdmod\mod集合` 并写进了 config.json，
        # 但跑着的进程仍然往旧的 `mod-test\mod-backup` 备份）。
        # 这里记下文件路径与 mtime；`config` 通过下面的 property 每次访问时比对，
        # 磁盘上变了就**重新读一遍**（并保留进程内动态改过的那些字段的语义：读进来就是最新的）。
        self._config_path = Path(self.config._config_path) if getattr(self.config, "_config_path", None) else None
        self._config_mtime = self._config_file_mtime()
        # 数据根（程序目录）被改名/搬走时，`AppConfig.load` 会把配置里残留的旧绝对路径
        # 自动改回相对路径 —— 这里留痕，排查"路径怎么变了"时有据可查
        # （用户 2026-10-02 群反馈：「我把主路径改了文件名，然后他没识别出来」）。
        for note in list(getattr(self.config, "_relocated", []) or []):
            launcher._append_log(self.config, f"数据根与配置里记录的不同，已自动纠正路径 {note}")
        self.config.ensure_dirs()
        # ⚠️⚠️ **下面这段原先缩进在 `config` 的 setter 里**（2026-10-04 修正）。
        #
        # 症状：它看起来是 `__init__` 的尾巴，其实整个函数体都属于
        # `@config.setter def config(...)` —— 因为 `__init__` 在 `self.config = load(...)`
        # 之后就没有语句了，后面那段 8 空格缩进的代码紧跟在 setter 的 `self._config = value`
        # 后面。为什么一直没炸：`__init__` 第 129 行那句赋值**本身就会触发 setter**，
        # 于是这些初始化"顺带"跑了一次 —— 靠巧合工作。
        #
        # 代价（真实后果）：任何 `api.config = xxx` 赋值（测试里就有、将来热重载也可能走）
        # 都会**重置正在进行的下载任务状态**（`_mod_dl` 变回空表）、清掉 Mod 列表缓存、
        # 换掉 `_ui_ready` 事件（正在等的预热线程永远等不到），并**再起一个预热线程**
        # （重复全盘扫描、重复拉公告/角色表）。现在归位：setter 只赋值。
        self._mods_cache = None
        self._dep_task: dict[str, Any] | None = None
        # Mod 下载（粘贴网址 → 并行下载 → 自动解压入库）：任务表 + 一把入库锁
        # （下载并行、解压入库串行 —— 用户 2026-10-02 要求"并行多线程下载"）
        self._mod_dl: dict[str, Any] = {"done": True, "items": [], "cancel": False, "pause": False}
        # 「下载中关窗口要弹窗提示」用（用户 2026-10-02）：用户在确认框里点了
        # 「仍然退出」后置 True，closing 事件就放行。
        self.exit_confirmed = False
        self._mod_dl_lock = threading.Lock()
        # 把用户的下载加速/线路偏好装进 fastnet（只在下载时生效，用完即放）
        try:
            from . import fastnet

            fastnet.set_policy(getattr(self.config, "download_boost", "auto"))
            fastnet.set_line_mode(getattr(self.config, "download_line", "auto"))
            # 代理：VPN 只对浏览器生效时，程序这边得单独配（用户 2026-10-02 实测确认）
            fastnet.set_proxy(getattr(self.config, "download_proxy", ""))
            if fastnet.proxy_in_use():
                launcher._append_log(self.config, f"下载代理: {fastnet.proxy_in_use()}")
        except Exception:  # noqa: BLE001
            pass
        # **构造函数必须快**：窗口是在它返回之后才创建的，这里做任何全盘扫描都会让
        # "加载页"迟迟不出现（用户要求"所有情况都要尽早展示加载页面"）。于是所有
        # 重活（深探测、清理上次更新残留）挪到后台预热线程：前端先看到加载页，
        # 预热完成后再刷新一次即可（2026-10-01 改）。
        #
        # 2026-10-01 追加修复（实测从零启动窗口要 9.8 秒）：预热里的全盘扫描会和
        # WebView2 初始化抢磁盘与 GIL —— 有 config 时 autofill 直接跳过探测所以很快，
        # 从零时才真扫，正好卡在 webview.start() 里。现在预热先等前端首屏就绪
        # （ui_ready()）再动手，最多等 15 秒。
        self._warm_done = False
        # 未读的"公告"（info/warning）：后台预热拉到、由 get_state 带给前端弹一次。
        # **异常状态预警（critical）不走这里** —— 它由 prelaunch_alerts() 在点「一键启动」时
        # 现拉现弹（每次都弹、强制停留，用户 2026-09-30 要求）。
        self._announcements: list[dict[str, Any]] = []
        self._ui_ready = threading.Event()
        # Mod 备份仓的后台状态（去重：同一时刻只跑一个打包任务）
        self._modbackup_lock = threading.Lock()
        self._modbackup_running = False
        self._warm_up_thread: threading.Thread | None = None
        self._start_warm_up()

    def _start_warm_up(self) -> None:
        """起（或复用）那个唯一的后台预热线程。

        抽出来是为了**不会再起第二个**：原来它写在 config setter 里，每次赋值都会多一个。
        已经有活着的预热线程时直接返回。
        """
        current = getattr(self, "_warm_up_thread", None)
        if current is not None and current.is_alive():
            return
        self._warm_up_thread = threading.Thread(target=self._warm_up, name="mc-warm-up", daemon=True)
        self._warm_up_thread.start()

    def ui_ready(self) -> dict[str, Any]:
        """前端首屏渲染完成后调用：这时才允许后台开始全盘探测。"""
        self._ui_ready.set()
        return {"ok": True}

    # ── 配置热重载（用户 2026-10-03：「改一下就读一次」）──────────────────────
    def _config_file_mtime(self) -> float:
        try:
            path = getattr(self, "_config_path", None)
            return path.stat().st_mtime if path else 0.0
        except OSError:
            return 0.0

    @property
    def config(self):
        """读取配置 —— **磁盘上变了就重新读一遍**。

        为什么这么做：`self.config` 原先只是启动时 load 的一份内存副本，用户改了设置
        （例如「Mod 备份目录」）之后，跑着的进程仍然按旧值干活，必须重启才生效 ——
        他实测遇到的就是这个（改成了 mod集合，却还往 mod-backup 备份）。
        判据用 **mtime**（比每次都读文件便宜），只有真的变了才重新 load；
        load 会顺带做路径自愈与默认值迁移，与启动时走的是同一条路。
        """
        mtime = self._config_file_mtime()
        path = getattr(self, "_config_path", None)
        if path and mtime and mtime != getattr(self, "_config_mtime", None):
            try:
                reloaded = AppConfig.load(path)
            except Exception:  # noqa: BLE001 —— 读坏了就继续用内存里这份，绝不因此崩
                return self._config
            self._config = reloaded
            self._config_mtime = mtime
            try:
                from . import fastnet

                fastnet.set_policy(getattr(reloaded, "download_boost", "auto"))
                fastnet.set_line_mode(getattr(reloaded, "download_line", "auto"))
                fastnet.set_proxy(getattr(reloaded, "download_proxy", ""))
            except Exception:  # noqa: BLE001
                pass
        return self._config

    @config.setter
    def config(self, value) -> None:
        """只赋值 —— 初始化逻辑一律在 `__init__` 里（见那边的说明）。"""
        self._config = value

    # ------------------------------------------------------------------
    # Mod 备份仓（用户 2026-10-01 要求）
    # ------------------------------------------------------------------
    def _backup_new_mods(self, *, log: Any = None, background: bool = False) -> dict[str, Any]:
        """把"库里还没备份过"的 Mod **整份复制**进 `<数据根>\\mod-backup\\`（纯备份、不打包）。

        用户原话：「在根目录下放一个文件夹做 mod 备份，这个文件夹**只增不减**，
        **只要见到新 mod，就打包 zip 放进去**」→ 随后改成「**改成不要打包，纯备份**」。
        所以：只往里加、从不删、已有备份跳过。
        `background=True` 时另起线程（扫描之后顺带触发，不挡界面）。
        """
        from . import modbackup

        def _note(message: str) -> None:
            launcher._append_log(self.config, message)
            if callable(log):
                log(message)

        if not modbackup.enabled(self.config):
            # 总开关关着（用户 2026-10-02 要求）：不复制、不建目录，也不写日志 ——
            # 关掉是用户的明确选择，不是故障，不该每扫一次就刷一行。
            return {"ok": True, "skipped": True, "reason": "disabled"}

        if background:
            def worker() -> None:
                try:
                    self._backup_new_mods()
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(target=worker, name="mc-mod-backup", daemon=True).start()
            return {"ok": True, "queued": True}

        with self._modbackup_lock:
            if self._modbackup_running:
                return {"ok": True, "skipped": True, "reason": "已有备份任务在跑"}
            self._modbackup_running = True
        try:
            state = modbackup.status(self.config)
            if state.get("overlaps_library"):
                _note(f"WARN Mod 备份：备份目录与 Mod 库/中转目录重叠，已跳过（{state['dir']}）")
                return {"ok": False, "reason": "backup_dir_overlaps_library", **state}
            mods = self._mods()
            result = modbackup.backup_all(self.config, mods, log=_note)
            if result.get("created"):
                total_mb = sum(Path(p).stat().st_size for p in result["created"] if Path(p).is_file()) / 1048576
                _note(f"Mod 备份：新增 {len(result['created'])} 个 Mod 备份（{total_mb:.1f} MB）→ {result['dir']}")
            if result.get("failed"):
                _note(f"WARN Mod 备份：{len(result['failed'])} 个打包失败（见上）")
            return {"ok": not result.get("failed"), **result}
        finally:
            with self._modbackup_lock:
                self._modbackup_running = False

    def mod_backup_status(self) -> dict[str, Any]:
        """备份仓现状（设置页显示）。"""
        from . import modbackup

        data = modbackup.status(self.config)
        data["configured"] = modbackup.configured_dir(self.config)
        data["running"] = self._modbackup_running
        try:
            data["pending"] = len(modbackup.pending(self.config, self._mods()))
        except Exception:  # noqa: BLE001
            data["pending"] = 0
        return data

    def set_mod_backup_dir(self, value: str = "") -> dict[str, Any]:
        """设置页「Mod 备份目录」（用户 2026-10-02 要求：备份目录能自行选择）。

        留空 = 回到默认（数据根下的 `mod-backup\\`）。校验、落盘、重叠拒绝都在
        `modbackup.set_backup_dir` 里做，这里只负责写日志并把最新状态回给界面。
        """
        from . import modbackup

        result = modbackup.set_backup_dir(self.config, value)
        if result.get("ok"):
            if result.get("changed"):
                launcher._append_log(
                    self.config,
                    f"Mod 备份目录已改为 {result['dir']}"
                    "（新目录里还没有备份，下次扫描后会把库里每个 Mod 整份复制过去；"
                    f"旧目录 {result.get('previous')} 里的备份原样留着）",
                )
            else:
                launcher._append_log(self.config, f"Mod 备份目录未变：{result['dir']}")
        elif result.get("message"):
            launcher._append_log(self.config, f"WARN Mod 备份目录未改：{result['message']}")
        return {**self.mod_backup_status(), **result}

    def set_mod_backup_enabled(self, enabled: bool = True) -> dict[str, Any]:
        """设置页「Mod 备份」总开关（用户 2026-10-02：「默认开，关了就不备份」）。

        关掉只影响"以后还备不备份"：**已有备份一个都不动**（只增不减是红线），
        重新打开后库里还没备份过的 Mod 会在下次扫描/一键启动时补上。
        切换时写一行日志 —— "关了以后什么都没发生"事后不好判断是不是开关的缘故。
        """
        from . import modbackup

        result = modbackup.set_enabled(self.config, bool(enabled))
        if result.get("ok"):
            if result.get("changed"):
                if enabled:
                    launcher._append_log(
                        self.config,
                        "Mod 备份已开启：库里新见到的 Mod 会整份复制到 "
                        f"{result.get('dir')}（只增不减，程序不会删那里的文件）",
                    )
                else:
                    launcher._append_log(
                        self.config,
                        "Mod 备份已关闭：不再复制任何 Mod（已有备份原样保留在 "
                        f"{result.get('dir')}，一个都不删）",
                    )
        elif result.get("message"):
            launcher._append_log(self.config, f"WARN Mod 备份开关未改：{result['message']}")
        return {**self.mod_backup_status(), **result}

    def choose_mod_backup_dir(self) -> dict[str, Any]:
        """弹系统「选择文件夹」对话框挑备份目录，挑完立即生效。

        用户 2026-10-02 要求「在设置里能自行选择备份目录」—— 手填路径与点按钮挑都支持。
        没有窗口 / 没有 pywebview 时如实返回失败，让用户改用手填（不做静默兜底）。
        """
        from . import modbackup

        try:
            import webview  # type: ignore
        except Exception:  # noqa: BLE001
            return {"ok": False, "message": "当前环境没有 pywebview，请直接在输入框里填路径"}
        # 统一走原生 helper（原来这里自己实现了一套，与 choose_path 重复）
        native = self._native_file_dialog(True, "选择 Mod 备份目录")
        if native.get("cancelled"):
            return {"ok": False, "cancelled": True, "message": "已取消"}
        if not native.get("ok"):
            return native
        current = modbackup.backup_dir(self.config)
        try:
            current.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return self.set_mod_backup_dir(str(native["path"]))

    def open_mod_backup_dir(self) -> dict[str, Any]:
        """打开备份文件夹（不存在就先建出来，免得点了没反应）。"""
        from . import modbackup

        target = modbackup.backup_dir(self.config)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"创建备份目录失败：{exc}"}
        return self.open_path_in_explorer(str(target))

    def _warm_up(self) -> None:
        """后台预热：全盘探测 + 清理上次自更新残留。**别把重活挪回 __init__。**"""
        self._ui_ready.wait(timeout=15)
        try:
            if self.config.autofill(deep=True):
                try:
                    self.config.save()
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"后台探测失败: {exc}")
            except Exception:  # noqa: BLE001
                pass
        # 上次自我更新留下的 .old/.new/vbs 残留，启动时清掉
        try:
            removed = selfupdate.cleanup_stale(self.config)
            if removed:
                launcher._append_log(self.config, f"清理上次更新残留: {', '.join(removed)}")
        except Exception:  # noqa: BLE001
            pass
        # 角色表：先接上"运行时更新版"（有就用），再在后台**非阻塞**地跟官网对一次
        # （用户 2026-09-30 要求：「管理器要带最新角色名…每次启动后非阻塞检查」）。
        # 24 小时内不重复请求；失败静默、绝不影响启动、更不会拖慢首屏。
        try:
            from . import character_sync, core

            core.set_characters_override(character_sync.latest_path(self.config))
            report = character_sync.sync(
                self.config,
                log=lambda message: launcher._append_log(self.config, message),
            )
            if report.get("changed"):
                launcher._append_log(
                    self.config,
                    f"角色表已更新：新增 {len(report.get('added') or [])} 位，"
                    f"当前共 {report.get('local_count')} 位（来源：官网）",
                )
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"角色表检查跳过: {exc}")
            except Exception:  # noqa: BLE001
                pass
        # 乳摇（SBM）角色参数：上游 Release 停在 v2.3.5（19 条，**没有提弗洛斯**），
        # 而仓库 main 已有 20 条。用户 2026-10-01 要求：「**在作者改之前，mod 管理器自行
        # 拉取新的参数文件**」。同样后台跑、24 小时节流、失败静默，而且**只补缺失的角色**
        # （不覆盖用户调过的幅度/频率），来源可用 config.sbm_data_source 指向自己的 fork。
        try:
            from . import sbm_data_sync

            report = sbm_data_sync.sync(
                self.config,
                log=lambda message: launcher._append_log(self.config, message),
            )
            if report.get("changed"):
                names = "、".join(str(x) for x in (report.get("added") or [])[:6])
                launcher._append_log(
                    self.config,
                    f"乳摇角色数据已补充：新增 {len(report.get('added') or [])} 个角色"
                    f"（{names}），来源 {report.get('repo')}@{report.get('ref')}",
                )
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"乳摇数据检查跳过: {exc}")
            except Exception:  # noqa: BLE001
                pass
        # Mod 备份仓（用户 2026-10-01 要求）：「在根目录下放一个文件夹做 mod 备份，
        # 这个文件夹只增不减，**只要见到新 mod，就（改成纯备份后）整份复制进去**」。
        # 放在预热线程里 = 不卡首屏；逐个 Mod 打包、失败只记一笔（大库第一次会跑一会儿，
        # 但界面全程可用）。已经有备份的 Mod 会直接跳过，所以之后的启动是毫秒级。
        try:
            self._backup_new_mods(log=lambda message: launcher._append_log(self.config, message))
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"Mod 备份跳过: {exc}")
            except Exception:  # noqa: BLE001
                pass
        # 公告 / 异常状态预警：仓库里的 alerts.json（走 api.github.com，失败静默、不吃启动时间）。
        # 这里只取**未读公告**（info/warning，弹一次、不锁启动）；critical 留给点「一键启动」时
        # 由 prelaunch_alerts() 现拉现弹（每次都弹 + 强制停留）。
        try:
            from . import alerts

            overview = alerts.overview(
                self.config,
                log=lambda message: launcher._append_log(self.config, message),
            )
            self._announcements = list(overview.get("announcements") or [])
            critical = list(overview.get("critical") or [])
            if self._announcements or critical:
                launcher._append_log(
                    self.config,
                    f"公告检查：未读公告 {len(self._announcements)} 条"
                    + (f"，异常状态预警 {len(critical)} 条（点「一键启动」时会强制确认）" if critical else ""),
                )
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"公告检查跳过: {exc}")
            except Exception:  # noqa: BLE001
                pass
        # 文件守护：记下"关键文件这次在不在"（**每次启动只采样一次**）。连续几次启动都缺
        # 就说明是被反复删掉的（多半是杀毒软件隔离），由 get_state 带给前端弹窗提醒。
        # 纯存在性检查、毫秒级、不下载任何东西 —— 绝不拖慢启动。
        try:
            from . import filewatch

            report = filewatch.scan(
                self.config,
                log=lambda message: launcher._append_log(self.config, message),
            )
            if not report.get("alert"):
                launcher._append_log(
                    self.config, f"文件守护: 盯了 {report.get('checked', 0)} 个关键文件，这次都在"
                )
        except Exception as exc:  # noqa: BLE001
            try:
                launcher._append_log(self.config, f"文件守护跳过: {exc}")
            except Exception:  # noqa: BLE001
                pass
        self._warm_done = True

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _mods(self):
        if self._mods_cache is None:
            self._mods_cache = core.scan_library(self.config.library_path, self.config.staging_mods_path)
        return self._mods_cache

    def _invalidate_mods(self) -> None:
        """只让 Mod 列表缓存失效。

        **绝不能在这里清 `self._dep_task`** —— 那是下载任务的进度状态，跟 Mod 列表
        没有关系。而本方法会在重新扫描 / 收编手动 Mod / 确认角色归属时被调用，
        用户「切到别的页面」就会触发扫描 → 任务状态被清成 None → 正在跑的下载线程
        下一句访问 `self._dep_task[...]` 直接崩掉，界面上看起来就是"切个页面下载就
        从头再来"。下载任务的清理交给它自己（worker 的 finally）。
        """
        self._mods_cache = None
        self._modfix_cache = {}

    def _enrich_modfix_state(self, payload: list[dict[str, Any]], mods: list[Any]) -> None:
        """给 Mod 列表补上「修复 / 可回滚」状态（卡片右下角「更多」菜单要用）。

        按 mod_id 缓存：`is_fixed()` 要扫 ini，每次 get_state 都重扫会拖慢界面；
        缓存随 `_invalidate_mods()` 一起清空。
        """
        from . import modfix

        cache = getattr(self, "_modfix_cache", None)
        if cache is None:
            cache = {}
            self._modfix_cache = cache
        for item, mod in zip(payload, mods):
            info = cache.get(mod.id)
            if info is None:
                try:
                    fixed = bool(modfix.is_fixed(mod.path)["fixed"])
                except OSError:
                    fixed = False
                info = {
                    "fixed": fixed,
                    "can_rollback": bool(modfix.list_backups(self.config, mod.id)),
                }
                cache[mod.id] = info
            item.update(info)

    # 最近被前端调用过的 API 名（环形缓冲，只用于报错时给上下文）
    _recent_calls: list[str] = []

    def __getattribute__(self, name: str):
        """给**前端能调到的每个公开方法**包一层：抛异常时把 traceback 记进日志。

        为什么需要（2026-10-03，来自一份外部诊断包）：日志里只有
        `[ui] 前端错误: rejection: 'NoneType' object has no attribute 'lstrip'`
        —— Python 侧的堆栈在 pywebview 边界就丢了，**定位不到是哪一行**，
        只能靠人肉去扫全文找可疑调用点。包一层之后，崩在哪一行直接写进日志。
        只对公开（不以 `_` 开头）的可调用属性生效，属性访问/内部方法不受影响。
        """
        attr = object.__getattribute__(self, name)
        if name.startswith("_") or not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            recent = object.__getattribute__(self, "_recent_calls")
            recent.append(name)
            del recent[:-8]
            try:
                return attr(*args, **kwargs)
            except Exception:  # noqa: BLE001 - 记完照旧抛出，行为不变
                import traceback

                try:
                    from . import diagnostics

                    diagnostics.log_event(
                        self.config,
                        f"后端异常 @ {name}(): {traceback.format_exc()}"[:4000],
                        category="ui",
                    )
                except Exception:  # noqa: BLE001 - 记录失败不能掩盖原异常
                    pass
                raise

        return wrapper

    def log_frontend_error(self, message: str) -> dict[str, Any]:
        """接收前端 JS 错误，写进控制器日志（前端崩了也能在后端看到原因）。"""
        from . import diagnostics

        recent = list(getattr(self, "_recent_calls", []) or [])
        context = f"（最近调用：{' → '.join(recent[-4:])}）" if recent else ""
        diagnostics.log_event(self.config, f"前端错误: {message}{context}"[:2000], category="ui")
        return {"ok": True}

    def component_addon_status(self) -> dict[str, Any]:
        """两个插件（DLSS5 / 第一人称）的 addon 启停状态。"""
        from . import launcher

        return {
            "status": launcher.component_addon_status(self.config),
            "config": {
                "dlss5_addon_enabled": bool(getattr(self.config, "dlss5_addon_enabled", True)),
                "firstperson_addon_enabled": bool(getattr(self.config, "firstperson_addon_enabled", True)),
            },
        }

    def set_component_addon(self, component: str, enabled: bool) -> dict[str, Any]:
        """单独启停 DLSS5 / 第一人称插件，并同步 XXMI 注入库。"""
        from . import launcher

        if component not in ("dlss5", "firstperson"):
            return {"ok": False, "message": f"未知组件: {component}"}
        # **按显卡代次闸门**（用户 2026-10-01 要求：「开启时检测机器，如果不是 50 系就默认关
        # dlss5，开启 dlss5 的时候弹窗说明拒绝」）—— DLSS5 首发只支持 RTX 50 系，40 系及更早
        # 的机器上它一帧都出不来（NGX 回 `0xBAD00001` FeatureNotSupported）。与其让它"开着但
        # 没用"，不如明确拒绝并说明原因；**拒绝时不写配置**，前端会把开关弹回去。
        if component == "dlss5" and enabled:
            from . import deviceinfo

            try:
                supported, gpu, reason = deviceinfo.dlss5_supported()
            except Exception:  # noqa: BLE001 - 探测失败不拦人
                supported, gpu, reason = True, "", ""
            if not supported:
                launcher._append_log(self.config, f"DLSS5 启用被拒绝（显卡不支持）: {gpu} —— {reason}")
                return {
                    "ok": False,
                    "rejected": "dlss5_unsupported_gpu",
                    "gpu": gpu,
                    "message": (
                        f"这台机器的显卡是 {gpu}，{reason}\n\n"
                        "所以这个开关不给你开 —— 开了也是白开：进游戏后面板会一直显示"
                        "「成功NR帧 0」和 `最新NR NGX结果 0xBAD00001`，还会让你误以为是装坏了。\n\n"
                        "等 NVIDIA 放开 RTX 40 系之后，这个开关会自动变得可用（到时更新一下就行）。"
                    ),
                }
        key = "dlss5_addon_enabled" if component == "dlss5" else "firstperson_addon_enabled"
        setattr(self.config, key, bool(enabled))
        self.config.save()
        result = launcher.set_component_addons(self.config, component, bool(enabled))
        # 两个都关 → 注入库里的底座会被移除；至少一个开 → 保持注入
        try:
            launcher.configure_dlss5_injection(self.config, enabled=True)
        except Exception as exc:  # noqa: BLE001
            result["warning"] = f"重写注入库失败: {exc}"
        launcher._append_log(
            self.config,
            f"{'DLSS5' if component == 'dlss5' else '第一人称'} 插件{'启用' if enabled else '停用'}"
            f"（移动 {len(result.get('moved') or [])} 个文件）",
        )
        return result

    def crash_bundle_status(self) -> dict[str, Any]:
        """前端轮询用：取走刚生成的崩溃包（含终末地日志的 zip），只提示一次。"""
        from . import crashwatch

        fresh = crashwatch.take_bundle()
        return {
            "watch": crashwatch.watch_state(),
            "fresh": fresh or None,
            "latest": crashwatch.latest_bundle(self.config),
        }

    def open_path_in_explorer(self, target: str) -> dict[str, Any]:
        """打开文件/文件夹（崩溃包用）。"""
        from . import diagnostics

        return diagnostics.open_path(self.config, Path(target))

    def crash_watch_state(self) -> dict[str, Any]:
        """崩溃监控线程状态。"""
        from . import crashwatch

        return crashwatch.watch_state()

    def prelaunch_risks(self) -> dict[str, Any]:
        """一键启动前的风险检查：这套 Mod 会不会崩（静态冲突 + 崩溃记忆）。

        前端在「一键启动」里、**拉起 XXMI 之前**调它；有风险就弹确认框说明是什么
        冲突、由用户决定"仍然启动 / 先去清理"（用户 2026-09-30 要求）。

        ⚠ 先做一次 :meth:`_prune_missing_selection`：用户手动删掉库里的文件之后，
        勾选里会留下"找不到的旧 id"，界面上显示"选中 0 个"却还在报冲突风险
        （2026-10-01 反馈的 bug）。
        """
        from . import crashwatch

        self._prune_missing_selection()
        return crashwatch.prelaunch_risks(self.config)

    def _prune_missing_selection(self) -> list[str]:
        """把"库里已经没有了、但还留在勾选里"的 Mod 清出去，返回被清掉的 id。

        为什么必须有（用户 2026-10-01 原话：「如果手动删 mod 库中文件，会导致 mod 库
        选中 0 个，但是启动提示崩溃风险」）：`selected_mods` 是**上次**的勾选快照，库里
        的文件被人手动删了就再也对不上；界面按扫描结果渲染 → 显示"选中 0 个"，可
        `runtime\\_state\\mod_conflicts.json` 里还躺着上一次算的冲突 → 启动前照样弹窗。

        代价说明：只改**勾选**与控制器自己的 staging 产物，**绝不碰 Mod 库**（数据安全红线）。
        """
        # ⚠ 必须先丢掉 Mod 列表缓存：`self._mods()` 是按扫描结果缓存的，用户手动删库
        #   文件不会让它失效 —— 拿旧缓存比对等于什么都没清（这正是这个 bug 隐蔽的地方）。
        self._invalidate_mods()
        try:
            existing = {mod.id for mod in self._mods()}
        except Exception:  # noqa: BLE001 - 扫描失败就当没有可清理的
            return []
        current = [str(item) for item in (self.config.selected_mods or [])]
        kept = [item for item in current if item in existing]
        dropped = [item for item in current if item not in existing]
        # 第二种现场（2026-10-01 一份真实反馈的诊断包）：**Mod 库里一个都没有**，
        # 可 `EFMI\Mods` 里还躺着一堆上次生成的 `MC_*` —— 自检拿它们互相一比就报
        # "Mod 资源冲突"，启动前弹窗，用户看到的是"我库里没有皮肤也报错"。
        # 所以除了勾选，还要看 staging 跟当前选择是否还对得上。
        stale = self._stale_staging(set(kept))
        if not dropped and not stale:
            return []
        if dropped:
            self.config.selected_mods = kept
            try:
                self.config.save()
            except (OSError, ValueError):
                pass
            launcher._append_log(
                self.config,
                f"勾选清理：Mod 库里有 {len(dropped)} 个勾选项已经不存在（文件被删/改名）"
                f"→ 已从勾选里去掉；剩余 {len(kept)} 个",
            )
        if stale:
            launcher._append_log(
                self.config,
                f"staging 与当前选择不一致：{len(stale)} 个上次生成的 MC_* 还留在 "
                f"{self.config.staging_mods_path}（库里已没有对应 Mod）→ 一起收掉",
            )
        # 旧的冲突结论不再对应当前这套 Mod → 作废，否则会被当成"仍然有风险"
        try:
            diagnostics.mod_conflict_state_path(self.config).unlink()
        except OSError:
            pass
        # staging 必须跟选择对齐：库里的文件被删了，可 `MC_<它>` 还在 Mods 里 —— 那份
        # 产物照样会被 EFMI 加载，于是"界面上没这个 Mod、游戏里却还在"。
        try:
            result = activation.stage_and_prepare(
                self.config.library_path,
                self.config.staging_mods_path,
                self.config.runtime_path,
                selected_ids=kept,
                prefer_internal_dependencies=self.config.prefer_internal_dependencies,
            )
            launcher._append_log(
                self.config,
                "已按剩下的勾选重建 staging（未勾选时清空；Mod 库未动）",
            )
            kept_manual = [str(name) for name in (result.get("kept_manual") or [])]
            if kept_manual:
                # 数据安全：这些是**用户自己**放进 Mods 的目录，我们一律不动，但要说出来
                launcher._append_log(
                    self.config,
                    f"保留 {len(kept_manual)} 个不是控制器生成的目录（你自己放进 Mods 的）："
                    + "、".join(kept_manual[:6])
                    + ("…" if len(kept_manual) > 6 else ""),
                )
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"重建 staging 失败（已跳过）: {exc}")
        self._invalidate_mods()
        return dropped

    def _stale_staging(self, kept_ids: set[str]) -> list[str]:
        """staging 里那些**与当前勾选对不上**的 `MC_*` 目录名（空勾选时 = 全部）。"""
        root = self.config.staging_mods_path
        if not root.is_dir():
            return []
        try:
            current = [
                item.name for item in root.iterdir()
                if item.is_dir() and item.name.startswith("MC_") and item.name != "MC_Controller"
            ]
        except OSError:
            return []
        if not current:
            return []
        if not kept_ids:
            return current
        try:
            expected = {
                f"MC_{core.safe_name(mod.group)}_{core.safe_name(mod.name)}"
                for mod in self._mods()
                if str(mod.id) in kept_ids
            }
        except Exception:  # noqa: BLE001 - 反查失败就不动 staging（宁可留着）
            return []
        return [name for name in current if name not in expected]

    def conflict_groups(self) -> dict[str, Any]:
        """当前 Mod 资源冲突的**结构化**列表（每组含涉及的 Mod 名与库内 id）。

        给前端「选择要保留的 Mod」弹窗用 —— 用户 2026-10-01 要求：「如果确定是皮肤冲突
        导致崩溃，弹窗加个选项，一键关闭其中一个（自行选择）… 再弹一个，选择要保留的，
        在冲突的中间下拉框选择要保留的，**每组冲突单独下拉框**」。

        数据直接取最近一次自检落盘的 `runtime\\_state\\mod_conflicts.json`（已算好的事实）
        —— 这是**用户主动处理**冲突的入口，不该像"启动前提示"那样按当前 staging 过滤：
        进 Mod 库页点一次「生成控制器」就会刷新这份结论。
        """
        return self._conflict_state_report()

    def _conflict_state_report(self) -> dict[str, Any]:
        """读回最近一次自检的冲突结论（自检没写过就返回空）。"""
        state = diagnostics.mod_conflict_state(self.config)
        conflicts = [str(item) for item in (state.get("conflicts") or [])]
        groups = [g for g in (state.get("groups") or []) if isinstance(g, dict)]
        if state.get("ok") is not False:
            conflicts, groups = [], []
        return {
            "ok": True,
            "groups": groups,
            "conflicts": conflicts,
            "checked_at": str(state.get("at_text") or ""),
        }

    def resolve_mod_conflicts(self, keep: list[str] | None = None) -> dict[str, Any]:
        """按用户的选择**取消勾选**冲突里没被保留的那些 Mod，然后重新生成控制器。

        用户 2026-10-01 要求：冲突时给"一键关闭其中一个（自行选择）"，弹窗里**每组一个
        下拉框**选要保留的。这里只改**勾选**（`selected_mods`）—— **绝不动用户的 Mod 库**
        （数据安全红线）；改完立刻跑一次 `prepare()` 把 staging 清干净，否则用户进游戏还是撞。
        """
        keep_ids = {str(item) for item in (keep or []) if str(item)}
        report = self._conflict_state_report()
        involved: list[str] = []
        for group in report.get("groups") or []:
            for entry in group.get("mods") or []:
                mod_id = str(entry.get("id") or "")
                if mod_id:
                    involved.append(mod_id)
        involved = list(dict.fromkeys(involved))
        if not involved:
            return {"ok": False,
                    "message": "当前没有可以自动处理的冲突（可能已经清过，或是手动放进 Mods 的目录）"}

        drop = [mod_id for mod_id in involved if mod_id not in keep_ids]
        if not drop:
            return {"ok": True, "changed": False, "dropped": [], "kept": sorted(keep_ids),
                    "message": "没有需要取消勾选的 Mod"}
        remaining = [mod_id for mod_id in (self.config.selected_mods or [])
                     if mod_id not in set(drop)]
        names = {mod.id: mod.name for mod in self._mods()}
        dropped_names = [names.get(mod_id, mod_id) for mod_id in drop]
        self.config.selected_mods = remaining
        self.config.save()
        self._invalidate_mods()
        launcher._append_log(
            self.config,
            f"冲突处理：取消勾选 {'、'.join(dropped_names)}（保留 {len(keep_ids)} 个），重新生成控制器")
        summary: dict[str, Any] = {"skipped": True}
        if remaining:
            result = self.prepare(remaining)
            summary = {
                "patch_count": result.get("patch_count"),
                "action_count": result.get("action_count"),
            }
        return {
            "ok": True,
            "changed": True,
            "dropped": drop,
            "dropped_names": dropped_names,
            "kept": sorted(keep_ids),
            "selected": remaining,
            "prepare": summary,
            "message": ("已取消勾选 " + "、".join(dropped_names)
                        + ("；并重新生成了控制器" if remaining else "；已无选中 Mod，跳过生成")),
        }

    # ------------------------------------------------------------------
    # 公告 / 异常状态预警（仓库里的 alerts.json）
    # ------------------------------------------------------------------
    def prelaunch_alerts(self) -> dict[str, Any]:
        """「一键启动」前的异常状态检查：有 critical 预警就必须强制确认。

        与 `prelaunch_risks`（Mod 冲突）的分工：**本方法的数据来自仓库里的 `alerts.json`**
        （作者随时改、不用发版），而且**每次点一键启动都返回**（不记已读、没有开关）；
        前端会强制停留 `hold_seconds` 秒，并给三个选项：还原配置 / 保持配置但不启动 / 仍然启动。
        """
        from . import alerts

        overview = alerts.overview(
            self.config,
            log=lambda message: launcher._append_log(self.config, message),
        )
        critical = list(overview.get("critical") or [])
        return {
            "blocking": bool(critical),
            "alerts": critical,
            "hold_seconds": int(overview.get("hold_seconds") or alerts.DEFAULT_HOLD_SECONDS),
        }

    def alert_action(self, alert_id: str = "", action: str = "") -> dict[str, Any]:
        """用户在异常状态弹窗里选的动作。

        * `restore` = **还原配置**（主选项）：关掉所有注入开关 + 把游戏目录第三方文件备份移走；
        * `hold` = 保持配置但不启动（什么都不动）；
        * `launch` = 仍然启动（只留日志痕迹）。
        """
        from . import alerts

        ident = str(alert_id or "").strip()
        choice = str(action or "").strip().lower()
        if choice == "restore":
            result = alerts.safe_mode(
                self.config, log=lambda message: launcher._append_log(self.config, message)
            )
            launcher._append_log(self.config, f"异常状态预警「{ident}」：用户选择「还原配置」")
            return {"ok": bool(result.get("ok")), "action": "restore", "result": result}
        if choice == "hold":
            launcher._append_log(self.config, f"异常状态预警「{ident}」：用户选择「保持配置但不启动」")
            return {"ok": True, "action": "hold"}
        launcher._append_log(self.config, f"异常状态预警「{ident}」：用户选择「仍然启动」")
        return {"ok": True, "action": "launch"}

    def undo_alert_safe_mode(self) -> dict[str, Any]:
        """撤销「还原配置」：把注入开关恢复成还原前的样子（游戏目录文件用「一键还原」搬回）。"""
        from . import alerts

        return alerts.undo_safe_mode(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )

    def announcements_seen(self, ids: list[str] | None = None) -> dict[str, Any]:
        """把弹过的公告标记为已读（**只对 info/warning 有意义**；critical 每次都要弹）。"""
        from . import alerts

        alerts.mark_seen(self.config, ids)
        seen = {str(i) for i in (ids or [])}
        self._announcements = [a for a in self._announcements if str(a.get("id")) not in seen]
        return {"ok": True, "remaining": len(self._announcements)}

    def _file_watchdog(self) -> dict[str, Any] | None:
        """关键文件被反复删掉时给前端的提醒（用户 2026-10-01 要求）。

        **只读**：只做存在性判断 + 读历史计数，不下载、不补齐（补齐是自检的事）。
        判定规则见 `filewatch` 模块开头；**弹窗挂在一键启动那条路上**（前端负责）。

        这里顺手调一次 `filewatch.scan()`：它自带"**每个进程只真正采样一次**"的节流，
        所以重复调用是空操作 —— 但能保证"刚打开管理器、后台预热还没跑完就点一键启动"
        时也拿得到本进程的采样结果，而不是少算一次。
        """
        try:
            from . import filewatch

            filewatch.scan(self.config)
            return filewatch.pending(self.config)
        except Exception:  # noqa: BLE001 —— 提醒功能坏掉绝不能影响界面
            return None

    def file_watchdog_ack(self, keys: list[str] | None = None) -> dict[str, Any]:
        """用户已经看过提醒 → 记下，避免下次启动重复弹同一件事。"""
        from . import filewatch

        return filewatch.ack(self.config, list(keys or []))

    # ── 杀毒软件（2026-10-04 用户要求：「杀毒有没有办法处理，或者检测加弹窗」）──────
    # 与 `filewatch` 分工：那个回答"我们的文件是不是反复不见了"，这里回答
    # "**杀毒对哪个文件动过手**"（Defender 隔离清单里的真实路径）以及
    # "**把该放过的目录加进白名单**"。
    def _antivirus_snapshot(self) -> dict[str, Any] | None:
        """**只读缓存**，绝不在这里跑 PowerShell。

        为什么：`get_state()` 是界面每次刷新都会走的热路径，而一条 Defender 查询要
        1~3 秒 —— 挂在这儿会让"打开管理器"这一下明显卡住（用户对启动慢很敏感）。
        真正的检测走 `antivirus_check()`（前端在启动页异步调一次）。
        """
        from . import antivirus

        return antivirus.cached()

    def antivirus_check(self) -> dict[str, Any]:
        """检测一次杀毒相关的事实，并按设置**顺手把白名单加好**。

        * 条数少、幂等、进程内只真跑一次（`antivirus.scan_once` 自带节流）；
        * 开关 `defender_exclusions_enabled` **默认开**（用户 2026-10-04：「3 默认开」）——
          发现该放过的目录不在白名单里就自动加上，而不是再弹一个窗让用户自己去点；
        * 非管理员 / 没有 Defender 时**如实返回 `supported=False`**，前端据此降级成"提示"。
        """
        from . import antivirus

        try:
            return antivirus.scan_once(self.config, log=lambda m: launcher._append_log(self.config, m))
        except Exception as exc:  # noqa: BLE001 —— 这条线坏掉绝不能影响启动
            return {"supported": False, "note": f"检测失败：{exc}", "detections": [],
                    "missing": [], "exclusions": [], "wanted": [], "applied": None,
                    "admin": False}

    def antivirus_apply_exclusions(self) -> dict[str, Any]:
        """手动把该放过的目录加进 Defender 白名单（弹窗上的按钮走这条）。"""
        from . import antivirus

        result = antivirus.apply_exclusions(
            self.config, log=lambda m: launcher._append_log(self.config, m))
        antivirus.reset_cache()          # 加了之后重新读一次，界面上的状态才是真的
        return result

    def antivirus_restore(self, path: str) -> dict[str, Any]:
        """把被隔离的文件从 Defender 隔离区还原回原位置。"""
        from . import antivirus

        return antivirus.restore(self.config, path, log=lambda m: launcher._append_log(self.config, m))

    def collect_crash_report(self) -> dict[str, Any]:
        """立刻收集一次崩溃现场并写成报告（不等游戏退出）。"""
        from . import crashwatch

        evidence = crashwatch.collect_evidence(self.config)
        path = crashwatch.write_report(self.config, evidence)
        return {
            "ok": True,
            "path": str(path),
            # ⚠️ **判据必须与包内报告 / 崩溃监控一致**（2026-10-02 修）：这里原本是
            # `bool(evidence.get("crash_sight"))` —— 那只表示"CrashSight 目录里有记录"，
            # 而游戏自己的 `reportException`（被捕获的异常）**每次运行都会打**，不等于崩溃。
            # 后果：正常退出也被判成「崩溃判定: CrashSight 记录到异常」，还会连带挂上
            # "Mod 资源冲突"的归因，让用户白去折腾 Mod（外部反馈 #11 就是这个现象：他的
            # 界面说崩溃，而同一份日志里写的是「未检测到崩溃（正常退出）」）。
            # 统一走 `crashwatch.is_crash`（只有真的上传了崩溃转储 uploadCrash 才算崩）。
            "crashed": crashwatch.is_crash(evidence),
            "crash_dirs": [c.get("report_dir") for c in (evidence.get("crashes") or [])],
        }

    def open_logs_dir(self) -> dict[str, Any]:
        from . import diagnostics

        return diagnostics.open_path(self.config, self.config.runtime_path / "logs")

    def shutdown(self) -> dict[str, Any]:
        """窗口关闭时收尾：停掉后台任务并释放引用，确保进程能干净退出。"""
        try:
            if self._dep_task:
                self._dep_task["running"] = False
        except Exception:  # noqa: BLE001
            pass
        try:
            from . import diagnostics

            stop = getattr(diagnostics, "stop_process_monitor", None)
            if callable(stop):
                stop(self.config)
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}

    def _dependency_report(self):
        mods = self._mods()
        selected = set(self.config.selected_mods or [])
        if selected:
            mods = [mod for mod in mods if mod.id in selected or mod.is_dependency]
        report = dependencies.dependency_report(
            self.config.library_path,
            mods,
            self.config.dependency_manifest_path,
        )
        report.setdefault("manifest", {}).update(runtime_deps.builtin_report(self.config))
        # 随包分发的 DLSS 运行库 / DLSS5 组件（压缩分卷，缺失时首次启动自动展开）
        try:
            report["manifest"].update(runtime_assets.asset_report(self.config))
        except Exception:  # noqa: BLE001
            pass
        # 有公开上游的 DLSS5 组件（可在依赖页一键在线安装）
        try:
            report["manifest"].update(dlss5_fetcher.component_report(self.config))
        except Exception:  # noqa: BLE001
            pass
        # 乳摇插件也作为一个依赖项出现在列表里（与其他依赖同构，不单列按钮）
        try:
            from . import secondary_motion as sbm_mod
            from . import updates as updates_mod

            state = sbm_mod.status(self.config)
            local = updates_mod._sbm_local_version(self.config)
            report["manifest"]["secondary_motion"] = {
                "display": "ShakingBreastManager（次级运动插件）",
                # 版本号读不到（工具目录没配 / 文件被删）时**只显示「已安装」** ——
                # 用户 2026-10-03：「已安装（版本号读不到）就不要显示版本号就行」。
                # 读不到版本是内部细节，摆到状态列里只会让人以为装坏了。
                "status": (f"v{local} 已安装" if (state["manager_exists"] and local)
                           else ("已安装" if state["manager_exists"]
                                 else "未安装（点上方「自动安装/更新」会从官方仓库拉取并装好）")),
                "present": bool(state["manager_exists"]),
                "required": False,
                "source": "GitHub Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics",
                "install_dir": state.get("tool_dir") or "",
            }
        except Exception:  # noqa: BLE001
            pass
        # 「本管理器」也作为一项依赖并列显示，而且**排在最上面**（用户要求）
        try:
            manifest = {"endfieldmodcontroller": self._app_dependency_entry()}
            manifest.update(report.get("manifest") or {})
            report["manifest"] = manifest
        except Exception:  # noqa: BLE001
            pass
        return report

    def _app_dependency_entry(self) -> dict[str, Any]:
        """把 EndfieldModController 自己也当成一项可更新的依赖（置顶显示）。"""
        from .version import REPO_URL, __version__

        exe = selfupdate.executable_path()
        entry: dict[str, Any] = {
            "display": "EndfieldModController（本管理器）",
            "source": REPO_URL,
            "install_dir": str(exe or "源码运行模式"),
            "present": True,
            "required": True,
            "needed": False,
            "enabled": True,
            "version": __version__,
            "status": f"v{__version__}",
            "is_app": True,
        }
        try:
            info = selfupdate.check_update(self.config, use_cache=True)
            latest = str(info.get("latest") or "")
            entry["latest"] = latest
            entry["update_available"] = bool(info.get("update_available"))
            if info.get("error"):
                entry["status"] = f"v{__version__}（检查失败：{info['error'][:40]}）"
            elif info.get("update_available"):
                entry["status"] = f"v{__version__} → v{latest} 可更新"
                entry["needed"] = True
            elif latest:
                entry["status"] = f"v{__version__} 已是最新"
        except Exception as exc:  # noqa: BLE001
            entry["status"] = f"v{__version__}（检查失败：{exc}）"
        return entry

    # ------------------------------------------------------------------
    # state and config
    # ------------------------------------------------------------------
    def get_config(self) -> dict[str, Any]:
        return self.config.to_dict()

    def first_run_state(self) -> dict[str, Any]:
        """判断"还没初始化"并给前端一段说明。

        用户 2026-10-01 要求：「第一次启动的时候要在启动后弹个弹窗，说明第一次未初始化，
        终末地启动可能失败，再次点击一键启动即可」。

        判据：三个内置组件里**任何一个没装**（或控制器产物没生成）就算未初始化。
        """
        from . import runtime_deps

        try:
            report = runtime_deps.builtin_report(self.config)
        except Exception:  # noqa: BLE001
            report = {}
        missing = [key for key, item in (report or {}).items() if not item.get("present")]
        controller_ready = (self.config.controller_dir / "controller.ini").is_file()
        return {
            "first_run": bool(missing) or not controller_ready,
            "missing_components": missing,
            # 用户 2026-10-01 要求：首次不要直接推"一键启动"，而是先问要不要引导。
            "onboarding_done": bool(getattr(self.config, "onboarding_done", False)),
        }

    def pending_update(self) -> dict[str, Any]:
        """有没有"已下载但还没安装"的更新包（用户选"稍后"时会留着它）。"""
        try:
            return selfupdate.pending_payload(self.config)
        except Exception as exc:  # noqa: BLE001
            return {"pending": False, "error": str(exc)}

    def get_state(self) -> dict[str, Any]:
        # 双保险：前端**必然**会调 get_state()，所以它一到就等于"界面活着"。
        # `_warm_up` 靠这个信号决定什么时候开始拉公告 / 角色表；只靠显式 ui_ready() 的话，
        # 哪天前端漏调一次，所有人就要白等满 15 秒（2026-10-03 实际就是这个情况）。
        self._ui_ready.set()
        from . import diagnostics, poser, secondary_motion

        # 留痕：用来判断前端是否真的完成了初始化（界面空白时先看这几行有没有）
        diagnostics.log_event(self.config, "UI 调用 get_state()", category="ui")
        mods = self._mods()
        mods_payload = [m.to_dict(include_actions=False) for m in mods]
        self._enrich_modfix_state(mods_payload, mods)
        # **不扫盘**：本方法跑在 GUI 线程上，扫盘会把窗口渲染一起冻住（详见
        # reshade_integration.detect_game_dir 的注释）。从零启动时这里返回 None，
        # 后台预热完成后前端会自动再刷一次，那时就能经 official_launcher 推断出来。
        game_dir = reshade_integration.detect_game_dir(self.config, allow_scan=False)
        render_api = reshade_integration.detect_render_api(game_dir) if game_dir is not None else "unknown"
        return {
            "config": self.config.to_dict(),
            # **主路径**（= 程序所在目录 = config.json / runtime / library 的基准）。
            # 设置页第一项显示它：用户把程序目录改名/搬走后，一眼就能看出程序认的是哪个
            # 目录（2026-10-02 群反馈：「我把主路径改了文件名，然后他没识别出来」）。
            "data_root": str(self.config.base_dir),
            "mods": mods_payload,
            "dependency_report": self._dependency_report(),
            "render_api": render_api,
            "controller_ready": (self.config.controller_dir / "controller.ini").is_file(),
            # 统一面板的现状（前端用它显示「整合 Mod 快捷键」滑块是否真的生效）。
            # 判据在 reshade_integration.panel_status —— 单一实现，别在这儿另写一套。
            "hotkey_panel": reshade_integration.panel_status(self.config),
            # Mod 备份仓现状（设置页显示"备份了几个、占多大、还差几个"）
            "mod_backup": self.mod_backup_status(),
            "reshade_addon_ready": (self.config.dlss5_path / reshade_integration.ADDON_NAME).is_file(),
            # 这三个探测**读缓存**，不在这里触发全盘扫描（否则加载页会被卡住十几秒）；
            # 缓存由后台预热线程填好，前端看到 warming=True 时会再刷新一次。
            # 有"已下载但没安装"的更新包时，前端启动后会问用户要不要现在装
            "pending_update": self.pending_update(),
            # 未初始化（组件没装齐/控制器没生成）时，前端启动后弹窗说明"再点一次一键启动"
            "first_run": self.first_run_state(),
            "warming": not self._warm_done,
            "detected_xxmi": cached_detect("xxmi"),
            "detected_migoto_loader": cached_detect("migoto"),
            "detected_official_launcher": cached_detect("launcher"),
            "dlss5_status": launcher.dlss5_injection_status(self.config),
            "component_addon_status": {
                "status": launcher.component_addon_status(self.config),
                "config": {
                    "dlss5_addon_enabled": bool(getattr(self.config, "dlss5_addon_enabled", True)),
                    "firstperson_addon_enabled": bool(getattr(self.config, "firstperson_addon_enabled", True)),
                },
            },
            "secondary_motion_status": secondary_motion.status(self.config),
            # Endfield Poser（摆姿 / MMD 播放插件）：状态 + 它自带摆姿页的只读状态
            "poser_status": poser.status(self.config),
            # Mod 修复工具是否就位（库页用它提示"找不到工具"的原因）
            "modfix_status": self.modfix_status(),
            # 未读的公告（info/warning）：前端首屏就绪后弹一次，**不锁启动**。
            # 异常状态预警（critical）不在这里 —— 见 prelaunch_alerts()。
            "announcements": list(self._announcements),
            # 关键文件被反复删掉（疑似杀毒软件）→ 前端弹窗建议加白名单（用户 2026-10-01 要求）。
            # 只读、轻量（十来次存在性判断），不在这里触发任何补齐动作。
            "file_watchdog": self._file_watchdog(),
            # 杀毒软件：Defender 处置过哪些**相关**文件 + 白名单缺不缺（2026-10-04 加）。
            # ⚠️ 这里**只读缓存**（`_antivirus_snapshot` 不跑 PowerShell）—— 真正的检测由前端
            # 在启动页异步调一次 `antivirus_check()`。一条 Defender 查询要 1~3 秒，挂在
            # 每次 state 刷新上会让"打开管理器"明显卡住（用户对启动慢很敏感）。
            "antivirus": self._antivirus_snapshot(),
        }
    def autodetect_paths(self) -> dict[str, Any]:
        """**自动检测外部程序路径并回填配置**（2026-10-03 补回归）。

        0.9.5 有「自动检测 XXMI」按钮，另外每次刷新状态时还会**静默回填**
        `detected_xxmi / detected_migoto_loader / detected_official_launcher`
        （旧 `app.js:1474-1491` + `asStoredPath`）。换代到 Vue 之后这两条全丢了
        （`grep detected_` 在现前端 **0 命中**）⇒ 即使内置了 XXMI，那三个路径框也会一直空着。

        现在把这件事收进后端统一做（前端不该拼路径）：
          * 依次调用 `config.auto_detect_*`（它们各自"工作区内嵌优先、再退外部安装"）；
          * 只回填**当前为空**的字段 —— 不覆盖用户显式填过的路径；
          * 存进 config 后 `save()`（写盘时会按 `save_config` 同一套规则做相对化/归一化）。
        """
        from . import config as _cfg

        detected = {
            "xxmi_launcher": _cfg.auto_detect_xxmi(refresh=True),
            "migoto_loader": _cfg.auto_detect_migoto_loader(refresh=True),
            "official_launcher": _cfg.auto_detect_official_launcher(refresh=True),
            "game_exe": _cfg.auto_detect_game_dir(refresh=True),
            "secondary_motion_dir": _cfg.auto_detect_secondary_motion(),
        }
        filled: dict[str, str] = {}
        skipped: dict[str, str] = {}
        for key, value in detected.items():
            if not value:
                continue
            if str(getattr(self.config, key, "") or "").strip():
                skipped[key] = value          # 已有值：只报告，不覆盖
            else:
                filled[key] = value
                setattr(self.config, key, value)
        try:
            self.config.normalize_blank_paths()
        except Exception:  # noqa: BLE001
            pass
        if filled:
            try:
                self.config.save()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "message": f"检测到了路径但写配置失败：{exc}",
                        "filled": filled, "skipped": skipped}
        return {"ok": True, "filled": filled, "skipped": skipped,
                "message": ("已回填 " + "、".join(filled) if filled
                            else "没有发现需要回填的空路径")}

    def save_config(self, data: dict[str, Any]) -> dict[str, Any]:
        self._invalidate_mods()
        known = set(self.config.to_dict().keys())
        for key, value in data.items():
            if key in known:
                setattr(self.config, key, value)
        # **「留空 = 自动」必须真的成立**（用户 2026-10-02：「全部放开吧」）：
        # 空串不能原样留着 —— `resolve_path("")` 会解析成**数据根本身**（`dlss5_dir` 空了，
        # `dlss5_path` 就变成数据根，DLSS5 直接失效）。先按默认值回填，再让 `autofill`
        # 把能自动推导的（内置 XXMI / ReShade 底座 / 乳摇 / Poser）补上，最后把补好的
        # 值一起返回给前端回显 —— 用户看到的就是"清空后它自己填回该有的样子"。
        self.config.normalize_blank_paths()
        self.config.autofill(deep=False)
        self.config.ensure_dirs()
        self.config.save()
        # 改了代理/加速偏好要**立刻生效**（不然用户填完还得重启才走代理）
        try:
            from . import fastnet

            fastnet.set_policy(getattr(self.config, "download_boost", "auto"))
            fastnet.set_line_mode(getattr(self.config, "download_line", "auto"))
            fastnet.set_proxy(getattr(self.config, "download_proxy", ""))
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "config": self.config.to_dict()}

    def set_hotkey_takeover(self, enabled: bool) -> dict[str, Any]:
        """启动页「游戏内 Mod 面板」开关的后端。

        用户 2026-10-01 原话：「开了要锁 mod 快捷键，注入 reshade」—— 而面板 2026-10-02
        换成了**直接发 Mod 自己原键**的形态（用户：「让面板走 mod 的按键」），锁键会让
        这条链路直接失效（见 `core.HOTKEY_LOCK_ENABLED` 的说明）。所以这个开关现在
        只做一件事：**把面板部署进 ReShade 会读的目录**；锁键动作已停用。
        """
        self.config.hotkey_takeover = bool(enabled)
        self.config.save()
        deploy: dict[str, Any] = {"warnings": [], "deployed": []}
        if enabled:
            deploy = reshade_integration.deploy_panel(
                self.config,
                self.config.controller_dir,
                log=lambda message: launcher._append_log(self.config, message),
            )
            # 面板里的中文要靠 ReShade 加载中文字体（默认字体只有 ASCII）
            reshade_integration.ensure_panel_font(
                self.config, log=lambda message: launcher._append_log(self.config, message)
            )
        status = reshade_integration.panel_status(self.config)

        reprepared = False
        running = False
        try:
            running = bool(self.game_running().get("running"))
        except Exception:  # noqa: BLE001
            running = False
        # 开到关 / 关到开都重新生成一次控制器：`actions.tsv` 会随勾选的 Mod 变，
        # 而且上一版（锁键还生效时）可能已经把 staging 里的 `key` 行改写成 `VK_F24`，
        # 重铺一次才是"面板拿到的就是现在的库"。
        if status["possible"] and not running:
            try:
                self.prepare()
                reprepared = True
            except Exception as exc:  # noqa: BLE001
                launcher._append_log(self.config, f"切换游戏内 Mod 面板后重新生成控制器失败: {exc}")

        if not enabled:
            message = "已关闭：下次启动不再铺面板（已经铺好的那份不删，Mod 自带按键一直照常生效）"
        elif not status["possible"]:
            message = f"面板用不了（{status['reason']}）—— Mod 自带按键照常生效"
        elif running:
            message = "已打开：退出游戏后点「一键启动」才会把面板铺进 ReShade（进游戏按 Home 打开）"
        elif reprepared:
            message = "已打开：面板已就位 —— 进游戏按 Home 打开，点按钮 = 按一次该 Mod 自己的按键"
        else:
            message = "已打开：下次「一键启动」时把面板铺进 ReShade"

        return {
            "ok": True,
            "enabled": bool(enabled),
            "possible": bool(status["possible"]),
            "ready": bool(status["ready"]),
            "reason": status["reason"],
            "panel": status,
            "warnings": deploy.get("warnings", []),
            "reprepared": reprepared,
            "game_running": running,
            "message": message,
        }

    # ------------------------------------------------------------------
    # library / activation
    # ------------------------------------------------------------------
    def scan(self) -> dict[str, Any]:
        from . import diagnostics

        self._invalidate_mods()
        mods = self._mods()
        diagnostics.log_event(self.config, f"UI 调用 scan() -> {len(mods)} 个 Mod", category="ui")
        # 「只要见到新 mod，就备份进备份仓」—— 扫描是"见到新 Mod"最自然的时机；
        # 打包放到后台线程，界面照常返回（已有备份的会直接跳过，通常是毫秒级）。
        try:
            self._backup_new_mods(background=True)
        except Exception:  # noqa: BLE001
            pass
        return {
            "mods": [m.to_dict(include_actions=False) for m in mods],
            "dependency_report": self._dependency_report(),
        }

    def get_mod_cover(self, mod_id: str) -> dict[str, Any]:
        for mod in self._mods():
            if mod.id != mod_id:
                continue
            if not mod.cover_path or not mod.cover_path.is_file():
                return {"ok": False, "message": "no cover"}
            suffix = mod.cover_path.suffix.lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".gif": "image/gif",
            }.get(suffix, "application/octet-stream")
            raw = b""
            try:
                from PIL import Image  # type: ignore
                with Image.open(mod.cover_path) as image:
                    image = image.convert("RGB")
                    image.thumbnail((480, 300))
                    buffer = io.BytesIO()
                    image.save(buffer, format="JPEG", quality=82, optimize=True)
                    raw = buffer.getvalue()
                    mime = "image/jpeg"
            except Exception:
                try:
                    raw = mod.cover_path.read_bytes()
                except OSError as exc:
                    return {"ok": False, "message": str(exc)}
            if len(raw) > 6 * 1024 * 1024:
                return {"ok": False, "message": "cover is too large"}
            return {
                "ok": True,
                "name": mod.cover_path.name,
                "data_uri": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"),
            }
        return {"ok": False, "message": "mod not found"}

    def prepare(self, active_ids: list[str] | None = None) -> dict[str, Any]:
        # active_ids 为 None 时沿用**"真正要 stage 的"选择**（`effective_selected_mods`：
        # 「皮肤 Mod」总开关关掉时返回空），避免无参调用（CLI / 自检）把选择清空，
        # 也避免"一键启动关了皮肤、再点一次生成控制器又把它装回去"。
        if active_ids is None:
            active_ids = list(self.config.effective_selected_mods)
        if not getattr(self.config, "efmi_injection", True):
            launcher._append_log(
                self.config, "皮肤 Mod 已关闭：本次生成控制器不放入任何皮肤（Mods 会清空）"
            )
        # ⚠️ 空列表**照样往下走**：`stage_and_prepare` 对显式空列表会清空 Mods
        #    （`_stage_empty`），而"全部激活"只在 `all_when_empty=True` 时才发生。
        #    以前这里"跳过 staging"，结果上一次的 `MC_*` 留着照样被 EFMI 加载（幽灵 Mod）。
        try:
            result = activation.stage_and_prepare(
                self.config.library_path,
                self.config.staging_mods_path,
                self.config.runtime_path,
                selected_ids=active_ids,
                # 默认 False：不改写 Mod 自带热键（见 activation.stage_and_prepare 的说明）
                hotkey_takeover=bool(getattr(self.config, "hotkey_takeover", False)),
                # 默认 False：保留同角色互斥；用户打开"强行关闭互斥"拨钮后放行同角色多个 Mod
                allow_same_character=bool(getattr(self.config, "allow_same_character_mods", False)),
                # 依赖去重/内外优先级（用户 2026-10-02）：默认内部（`_deps\`）优先
                prefer_internal_dependencies=bool(
                    getattr(self.config, "prefer_internal_dependencies", True)
                ),
            )
        except activation.LibraryGuardError as exc:
            # "不要动用户的 Mod 库"（用户 2026-10-01 硬规则）：staging 与库重叠时拒绝执行。
            # 这里转成一句可读的界面提示，而不是抛一堆栈给前端。
            launcher._append_log(self.config, f"已拒绝 staging（保护 Mod 库）: {exc}")
            return {
                "ok": False,
                "message": str(exc),
                "blocked": "library_overlap",
                "patch_count": 0,
                "action_count": 0,
                "controller_dir": str(self.config.controller_dir),
                "reshade_dir": "",
                "user_ini_path": str(self.config.user_ini_path),
                "reshade_addon": "",
            }
        # 皮肤总开关关掉时 `active_ids` 是空的（那是"不加载"的意思）——
        # **别把用户自己的勾选清掉**，否则他在界面上会看到勾选全没了。
        if getattr(self.config, "efmi_injection", True):
            self.config.selected_mods = list(active_ids)
        self.config.save()
        # 依赖的账要写进日志（用户 2026-10-02 要求"去重 + 内外部优先级"）：用了哪一份、
        # 屏蔽了哪几份、为什么 —— 不写的话界面上只会"少一个 Mod"，用户无从判断。
        for line in activation.dependency_note(result.get("activation") or {}):
            launcher._append_log(self.config, line)
        # ⚠️ 空选择（皮肤总开关关掉 / 一个都没勾）时 `stage_and_prepare` 走的是 `_stage_empty`
        #    分支，**返回的字典里没有 `actions_manifest`** —— 以前这里能早退，所以从没暴露；
        #    现在改成"一律往下走清空"，就必须容错（2026-10-02 被新测试当场逮到）。
        actions = ((result.get("actions_manifest") or {}).get("actions")) or []
        controller_dir = result.get("controller_dir") or str(self.config.controller_dir)
        reshade_info = launcher.prepare_reshade_runtime(self.config, Path(controller_dir))
        launcher._append_log(
            self.config,
            f"prepare complete: actions={len(actions)} patches={int(result.get('patch_count') or 0)}",
        )
        return {
            "activation": result.get("activation") or {},
            "patch_count": int(result.get("patch_count") or 0),
            "action_count": len(actions),
            "controller_dir": controller_dir,
            "activation_reshade_dir": result.get("reshade_dir") or "",
            "user_ini_path": result.get("user_ini_path") or str(self.config.user_ini_path),
            "reshade_addon": reshade_info.get("addon", ""),
            # 注意：这个键原先在同一个 dict 字面量里出现两次（371 行被 374 行静默覆盖），
            # staging 的结果永远看不到 —— 2026-10-01 拆成 activation_reshade_dir + reshade_dir。
            "reshade_dir": reshade_info.get("reshade_dir", ""),
        }

    # ------------------------------------------------------------------
    # dependencies
    # ------------------------------------------------------------------
    def dependency_status(self) -> dict[str, Any]:
        return self._dependency_report()

    def update_dependencies(self, dry_run: bool = True) -> dict[str, Any]:
        manifest = dependencies.load_manifest(self.config.dependency_manifest_path)
        results = dependencies.update_all(manifest, self.config.library_path, dry_run=dry_run)
        return {"dry_run": dry_run, "results": [r.__dict__ for r in results]}

    def start_dependency_update(self, dry_run: bool = False, only_missing: bool = False, include_builtin: bool = False) -> dict[str, Any]:
        if self._dep_task and self._dep_task.get("running"):
            return self.get_dependency_progress()
        self._dep_task = {
            "running": True,
            "dry_run": dry_run,
            "only_missing": only_missing,
            "include_builtin": include_builtin,
            "current": 0,
            "total": 0,
            "percent": 0.0,
            "message": "准备安装缺失依赖..." if only_missing else "准备中...",
            "log": [],
            "results": [],
        }

        progress, byte_progress, bump = self._make_dep_progress()

        def worker() -> None:
            assert self._dep_task is not None
            try:
                if include_builtin:
                    self._dep_task["total"] = 3          # 只有 XXMI / XXMI-Libs / EFMI
                    self._dep_task["current"] = 0
                    # 同上：显式点「安装内置组件」也要真的装（force=True）
                    results = runtime_deps.ensure_all(self.config, progress, force=True,
                                                          log=lambda m: launcher._append_log(self.config, m))
                    self._dep_task["results"] = [result.__dict__ for result in results]
                    self._dep_task["current"] = len(results)
                    self._dep_task["percent"] = 100.0
                    self._dep_task["message"] = "内置运行环境已处理"
                    return
                manifest = dependencies.load_manifest(self.config.dependency_manifest_path)
                if only_missing:
                    mods = self._mods()
                    selected = set(self.config.selected_mods or [])
                    if selected:
                        mods = [mod for mod in mods if mod.id in selected or mod.is_dependency]
                    required = core.collect_required_dependency_names(mods)
                    manifest = dependencies.select_missing_dependencies(manifest, self.config.library_path, required)
                # 本次要处理的依赖项数就是分母（这条路径只装依赖清单，不含其它阶段）
                self._dep_task["total"] = max(len(manifest), 1)
                self._dep_task["current"] = 0
                results = dependencies.update_all(
                    manifest,
                    self.config.library_path,
                    dry_run=dry_run,
                    progress=progress,
                    byte_progress=byte_progress,
                )
                self._dep_task["current"] = len(results)
                # 完成时对齐：保证"100%"和"N/N 项"一致（过程中不动分母，见 stage/进度回调）
                self._dep_task["total"] = max(len(results), 1)
                self._dep_task["results"] = [r.__dict__ for r in results]
                self._dep_task["percent"] = 100.0
                self._dep_task["message"] = "完成"
            except Exception as exc:  # noqa: BLE001
                self._dep_task["message"] = f"失败: {exc}"
                self._dep_task["log"].append(f"失败: {exc}")
            finally:
                self._dep_task["running"] = False

        threading.Thread(target=worker, name="mc-dependency-update", daemon=True).start()
        return self.get_dependency_progress()

    def _make_dep_progress(self):
        """构造 (progress, byte_progress, bump) 三件套，供依赖任务使用。

        全局进度 = **已完成项数 / 预估总项数**，覆盖全部下载阶段：随包资产、
        XXMI/XXMI-Libs/EFMI、DLSS5 在线组件、依赖清单、乳摇。

        为什么这么做（2026-10-01 用户反馈「进度条和实际下载不符，现在进度条只管 3 个组件，
        我需要全都管」）：以前每个模块通过 `progress(current, total, …)` **各自覆盖**
        `task["total"]`，谁最后调用谁说了算 —— 最后调的是 `runtime_deps.ensure_all`（它报
        `total=3`），于是进度条就只剩"3 个组件"。现在各模块报的 (current,total) **只用于
        显示"当前在做什么"**，全局进度改由 `bump()` 按实际完成的项数累加。
        """

        def progress(current: int, total: int, key: str, status: str) -> None:
            task = self._dep_task
            if task is None:
                return
            task["message"] = f"{key}: {status}"
            task["log"].append(f"{key}: {status}")

        def byte_progress(index: int, total: int, key: str, received: int, expected: int) -> None:
            task = self._dep_task
            if task is None:
                return
            done = int(task.get("current", 0))
            total_items = max(int(task.get("total", 0)), 1)
            inner = (received / expected) if expected else 0.0
            # **字节口径**：累计"已下字节 / 预期总字节"，前端进度条优先用它 ——
            # 用户 2026-10-03：「进度条不要一卡一卡的，应该跟着实际大小走」。
            # 原因：项数口径下 138 MB 的资产包**只算 1 项**，进度条涨到 1/N 就停住，
            # 直到那一项整个下完才跳一下，看起来就是"一卡一卡"。
            task["computed_bytes"] = int(task.get("computed_bytes", 0)) + int(received)
            if expected:
                task["expected_bytes"] = int(task.get("expected_bytes", 0)) + int(expected)
            # 项数口径保留（某些下载拿不到 Content-Length 时它仍可用）
            task["percent"] = min(99.0, (done + min(max(inner, 0.0), 1.0)) / total_items * 100.0)
            exp_all = int(task.get("expected_bytes", 0))
            if exp_all > 0:
                # ⚠️ **取一位小数**（2026-10-03 用户报「23.76781745624384% 这是什么百分数」）——
                # 原来这里直出浮点，前端模板 `{{ percent }}%` 原样显示一长串小数。
                # 后端保留一位（内部排序/比较够用），**显示一律由前端取整**。
                task["byte_percent"] = round(min(99.0, task["computed_bytes"] / exp_all * 100.0), 1)
            if expected:
                task["message"] = f"{key}: {received / 1048576:.1f}/{expected / 1048576:.1f} MB"
            else:
                task["message"] = f"{key}: 下载中 {received / 1048576:.1f} MB"

            # 实时速度（依赖页顶部那个卡片）：用前后两次采样的字节差 / 时间差。
            # 指数平滑一下，否则数字会随每个分块剧烈跳动、看不出趋势。
            import time as _t

            now = _t.time()
            prev_bytes, prev_at = task.get("_speed_bytes"), task.get("_speed_at")
            if prev_bytes is not None and prev_at is not None and now > prev_at:
                instant = (int(received) - int(prev_bytes)) / (now - prev_at)
                if instant >= 0:
                    old_speed = float(task.get("speed_bps") or 0.0)
                    task["speed_bps"] = instant if old_speed <= 0 else old_speed * 0.6 + instant * 0.4
            task["_speed_bytes"] = int(received)
            task["_speed_at"] = now
            task["bytes_received"] = int(received)

        def bump(count: int = 1, label: str = "") -> None:
            """某个阶段完成：把已完成项数加上 count 并刷新全局进度。"""
            task = self._dep_task
            if task is None:
                return
            task["current"] = int(task.get("current", 0)) + max(int(count), 0)
            task["total"] = max(int(task.get("total", 0)), task["current"], 1)
            task["percent"] = min(99.0, task["current"] / task["total"] * 100.0)
            if label:
                task["message"] = label

        return progress, byte_progress, bump

    def _estimate_update_total(self) -> int:
        """预估"一键更新"总共要处理多少项（用于进度条的分母）。"""
        # ⚠️ 2026-10-03 校准：**不要写 `len(...) or 1`**。
        # 用户实测「一键更新完成：实际 14 项，预估 9 项（预估公式待校准）」，
        # 我把 dry_run 的 14 项真值逐项对齐后发现：随包资产(5) + 内置(4) + dlss5 组件(3)
        # + 乳摇(1) + Poser(1) = 14 **完全正确**，多出来的那一项就是
        # `len(依赖清单) or 1` —— 清单为空时 `0 or 1` **凭空加了 1 项**。
        # 依赖清单为空 = 真的没有要处理的依赖项，就该加 0。
        est = 0
        try:
            est += len(runtime_assets.manifest_entries(self.config))
        except Exception:  # noqa: BLE001 - 读不到就当没有，别虚报
            pass
        if self.config.use_builtin_runtime:
            est += 4                                  # XXMI / XXMI-Libs / EFMI / Poser
        est += len(dlss5_fetcher.COMPONENTS)          # ReShade 底座 / DLSS5-Feeder / iMMERSE
        try:
            est += len(dependencies.load_manifest(self.config.dependency_manifest_path))
        except Exception:  # noqa: BLE001
            pass
        est += 1                                      # 乳摇（第三方工具）
        est += 1                                      # Endfield Poser（第三方插件）
        return max(est, 1)

    def start_full_update(self, dry_run: bool = False) -> dict[str, Any]:
        if self._dep_task and self._dep_task.get("running"):
            return self.get_dependency_progress()
        self._dep_task = {
            "running": True,
            "dry_run": dry_run,
            "only_missing": False,
            "include_builtin": True,
            "full": True,
            "current": 0,
            "total": 0,
            "percent": 0.0, "byte_percent": 0.0, "computed_bytes": 0, "expected_bytes": 0,
            "message": "准备自动安装/更新...",
            "log": [],
            "results": [],
        }

        progress, byte_progress, bump = self._make_dep_progress()

        def worker() -> None:
            assert self._dep_task is not None
            from types import SimpleNamespace as _NS
            try:
                # 全局进度分母：**一开始就按"实际要处理的项数"算好，中途不再变动**。
                # 用户 2026-10-01 反馈「从 0 开始最开始是共 11 项，然后 12 项搞好又变成 12 项」
                # —— 原因是用"预估"当分母，而真实运行时会按"只装缺失的"过滤依赖项，
                # 到结束时我又把分母校正成实际值，于是数字中途跳变。现在提前算准。
                manifest_all = dependencies.load_manifest(self.config.dependency_manifest_path)
                mods_for_deps = self._mods()
                selected_for_deps = set(self.config.selected_mods or [])
                if selected_for_deps:
                    mods_for_deps = [m for m in mods_for_deps
                                     if m.id in selected_for_deps or m.is_dependency]
                required_names = core.collect_required_dependency_names(mods_for_deps)
                missing_specs = dependencies.select_missing_dependencies(
                    manifest_all, self.config.library_path, required_names)
                combined_specs = {key: spec for key, spec in manifest_all.items() if spec.enabled}
                combined_specs.update(missing_specs)
                try:
                    # ⚠️ **不要写 `len(...) or 1`**（2026-10-04 修）：清单为空 = 真的没有要
                    # 处理的项，`0 or 1` 会**凭空把分母加 1**，于是完成时"100%"和"N/N 项"
                    # 对不上（多出的一项永远补不齐）。`_estimate_update_total()` 里已经因为
                    # 同一个写法踩过一次并留了注释，这里是漏改的同一处。
                    asset_count = len(runtime_assets.manifest_entries(self.config))
                except Exception:  # noqa: BLE001
                    asset_count = 0
                self._dep_task["total"] = max(
                    len(combined_specs), 1,
                ) + 3 + len(dlss5_fetcher.COMPONENTS) + asset_count + 1
                # 把预估值单独留一份：完成时用它和实际项数比对，差得多就说明预估公式要校准
                self._dep_task["estimated_total"] = self._dep_task["total"]
                self._dep_task["current"] = 0
                results = []
                # 每阶段新增了几项：写进日志，用来校准"分母应该固定成多少"。
                # 用户要求「总项目应该是固定值，如果检查了没问题也计入」—— 要满足它，
                # 就得先知道哪个阶段最后少产出了条目（见完成分支的比对日志）。
                _stage_mark = [0]

                def stage_done() -> None:
                    """一个阶段跑完：把"已完成项数"设为当前累计的结果条数。

                    用**绝对量**（`len(results)`）而不是增量，重复调用也安全。
                    """
                    task = self._dep_task
                    if task is None:
                        return
                    added = len(results) - _stage_mark[0]
                    _stage_mark[0] = len(results)
                    task["current"] = len(results)
                    task["total"] = max(int(task.get("total", 0)), len(results), 1)
                    task["percent"] = min(99.0, len(results) / task["total"] * 100.0)
                    task["log"].append(
                        f"阶段完成：新增 {added} 项，累计 {len(results)}/{task['total']} 项"
                    )
                # ① 随包分发的 DLSS 运行库（压缩分卷）：离线可用，缺失/损坏才展开。
                #    放在最前 —— 后面的 DLSS5 组件与游戏目录补齐都可能用到它。
                try:
                    if dry_run:
                        for name, item in runtime_assets.asset_report(self.config).items():
                            results.append(_NS(
                                key=f"nvngx:{name}",
                                status=str(item.get("status") or ""),
                                message=f"内置 {item.get('packed') or ''}".strip(),
                            ))
                    else:
                        for asset in runtime_assets.ensure_all(
                            self.config,
                            log=lambda line: self._dep_task["log"].append(line),
                        ):
                            results.append(_NS(
                                key=f"nvngx:{asset.name}",
                                # 状态口径：只有真正的 error/failed 才算"失败"；
                                # missing / missing_source / skipped 属于"缺/跳过"，
                                # 不该被统计进"完成，但有 N 项失败"（2026-10-01 修）。
                                status={
                                    "present": "已就位", "extracted": "已展开",
                                    "missing": "缺失", "missing_source": "缺少资产包",
                                    "skipped": "跳过", "error": "失败", "failed": "失败",
                                }.get(str(asset.status), str(asset.status) or "完成"),
                                message=asset.message,
                            ))
                except Exception as exc:  # noqa: BLE001
                    results.append(_NS(key="nvngx", status="失败", message=str(exc)))
                stage_done()
                if self.config.use_builtin_runtime:
                    if dry_run:
                        results.extend(runtime_deps.dry_run_results(self.config))
                    else:
                        # BuiltinResult 的 status 是英文（installed/up_to_date/error…），
                        # 前端按"失败"两个字统计失败项，直接塞进去会**漏报**；这里统一成中文
                        # （2026-10-01 修：用户看到"完成，但有 1 项失败"却不知道是哪一项）。
                        # force=True：用户在依赖页**亲手点**的「一键更新全部组件」是显式指令，
                        # 不受「启动时自动更新」开关限制（2026-10-03 修「告诉我更新完了，
                        # 但是一键启动又说没有」—— 这条没传 force 时，关着那个开关的用户点了
                        # 更新也只会"检查不下载"，界面报完成、组件还是旧的）。
                        for item in runtime_deps.ensure_all(self.config, progress, byte_progress,
                                        log=lambda m: launcher._append_log(self.config, m),
                                        force=True):
                            results.append(_NS(
                                key=item.key,
                                status={
                                    "installed": "已安装", "up_to_date": "已是最新",
                                    "present": "已就位", "skipped": "跳过",
                                    "error": "失败", "failed": "失败", "missing": "缺失",
                                }.get(str(item.status), str(item.status) or "完成"),
                                message=item.message,
                                version=item.version,
                                path=item.path,
                            ))
                stage_done()
                # ② DLSS5 组件：有公开上游的那几个（ReShade 底座 / DLSS5-Feeder / iMMERSE shader）
                try:
                    if dry_run:
                        for key, item in dlss5_fetcher.component_report(self.config).items():
                            results.append(_NS(
                                key=key,
                                status=str(item.get("status") or ""),
                                message=str(item.get("source") or ""),
                            ))
                    else:
                        for item in dlss5_fetcher.ensure_all(
                            self.config,
                            log=lambda line: self._dep_task["log"].append(line),
                        ):
                            results.append(_NS(
                                key=str(item.get("key") or "dlss5"),
                                status=str(item.get("status") or "完成"),
                                message=str(item.get("message") or ""),
                            ))
                except Exception as exc:  # noqa: BLE001
                    results.append(_NS(key="dlss5", status="失败", message=str(exc)))
                stage_done()
                # 复用开头已算好的清单（分母就是按它定的，别再重复算一遍）
                manifest = manifest_all
                combined = combined_specs
                results.extend(dependencies.update_all(
                    combined,
                    self.config.library_path,
                    dry_run=dry_run,
                    enabled_only=False,
                    progress=progress,
                    byte_progress=byte_progress,
                ))
                stage_done()
                # 乳摇插件（第三方工具）也走同一个更新流程，不再单列按钮
                try:
                    from types import SimpleNamespace

                    from . import updates as updates_mod

                    # ⚠️ 这里原是 `log=progress and None` —— `progress` 是函数（恒真），
                    # `and None` 让整个表达式**恒等于 None**，等于白写一句。语义就是"不传日志
                    # 回调"（进度由 progress/byte_progress 两条通道上报）。改成显式 None。
                    ureport = updates_mod.check_updates(self.config, log=None)
                    sm = ureport.get("secondary_motion") or {}
                    current = sm.get("current") or ""
                    latest = sm.get("latest") or ""
                    download_url = sm.get("download_url") or ""
                    # 「没装就装上」+「有新版就更新」。之前只判断 update_available，
                    # 于是本机**根本没装**时反被判成"已是最新"，用户看到的却是"未找到工具目录"。
                    need_install = not current
                    need_update = bool(current and latest and sm.get("update_available"))
                    if (need_install or need_update) and download_url:
                        if dry_run:
                            results.append(SimpleNamespace(
                                key="secondary_motion",
                                status="待安装" if need_install else "可更新",
                                message=(f"未安装 → {latest}" if need_install else f"{current} → {latest}"),
                            ))
                        else:
                            outcome = updates_mod.update_secondary_motion(self.config, url=download_url)
                            results.append(SimpleNamespace(
                                key="secondary_motion",
                                status=(("已安装" if need_install else "已更新")
                                        if outcome.get("ok") else "失败"),
                                message=outcome.get("message") or outcome.get("note", ""),
                            ))
                    else:
                        results.append(SimpleNamespace(key="secondary_motion", status="已是最新",
                                                       message=f"v{current or '?'}"))
                    # Endfield Poser（摆姿 / MMD 播放）：与乳摇同一条更新流程、共用上面
                    # 那次 check_updates 结果（不重复联网）。这一步只负责把安装包下到
                    # runtime\poser；游戏目录里的文件由启动时的自检调它自己的安装向导补齐。
                    try:
                        from . import poser as poser_mod

                        pp = ureport.get("poser") or {}
                        current_p = str(pp.get("current") or "")
                        latest_p = str(pp.get("latest") or "")
                        need_install_p = not current_p
                        need_update_p = bool(current_p and latest_p and pp.get("update_available"))
                        if need_install_p or need_update_p:
                            if dry_run:
                                results.append(SimpleNamespace(
                                    key="poser",
                                    status="待安装" if need_install_p else "可更新",
                                    message=(f"未安装 → {latest_p}" if need_install_p
                                             else f"{current_p} → {latest_p}")))
                            elif not getattr(self.config, "poser_injection", True):
                                results.append(SimpleNamespace(key="poser", status="跳过",
                                                               message="启动页已关闭该组件"))
                            else:
                                outcome = poser_mod.ensure_pack(self.config)
                                results.append(SimpleNamespace(
                                    key="poser",
                                    status="已安装" if outcome.get("ok") else "失败",
                                    message=str(outcome.get("message") or outcome.get("version") or "")))
                        else:
                            results.append(SimpleNamespace(key="poser", status="已是最新",
                                                           message=latest_p or current_p or "?"))
                    except Exception as exc:  # noqa: BLE001
                        results.append(SimpleNamespace(key="poser", status="跳过", message=str(exc)))
                except Exception as exc:  # noqa: BLE001
                    from types import SimpleNamespace as _NS

                    results.append(_NS(key="secondary_motion", status="跳过", message=str(exc)))
                # 完成：**把分子分母对齐到实际完成项数**，保证"100%"和"N/N 项"一定一致。
                # ⚠️ 这里踩过两次、两个要求必须同时满足：
                #   ① 过程中分母不许变（用户「从 0 开始最开始是共 11 项，然后 12 项搞好又变成
                #      12 项」）→ 过程中只上调、不下调，见 stage_done()；
                #   ② 完成时"100%"必须和"N/N"对得上（用户 2026-09-29 实测反馈「现在显示的是
                #      100% · 已完成 12/13 项」）→ 预估分母比实际项数多时，在**最后一刻**对齐。
                #      此时进度已经结束，不会造成过程中跳变。
                done_items = len(results)
                self._dep_task["results"] = [result.__dict__ for result in results]
                self._dep_task["current"] = done_items
                self._dep_task["total"] = max(done_items, 1)
                self._dep_task["percent"] = 100.0
                # ⚠️⚠️ **`byte_percent` 也要一起对齐**（2026-10-03 用户报
                #     「**动态显示安装完成，但是进度条才走了一半**」）。
                # 原因：前端进度条**优先用 `byte_percent`**（DepsPage.vue:234），
                # 而它原先只按"预估总字节"算 —— 预估偏大时就永远走不到 100。
                # 这里完成即终态，把它和 `expected_bytes` 一并收敛到实际值，
                # 免得"字节数"那一行也停在半路。
                self._dep_task["byte_percent"] = 100.0
                self._dep_task["bytes_received"] = int(
                    self._dep_task.get("computed_bytes")
                    or self._dep_task.get("bytes_received") or 0)
                self._dep_task["expected_bytes"] = int(
                    self._dep_task.get("computed_bytes")
                    or self._dep_task.get("expected_bytes") or 0)
                self._dep_task["message"] = "完成"
                estimated = int(self._dep_task.get("estimated_total") or 0)
                if estimated and estimated != done_items:
                    self._dep_task["log"].append(
                        f"一键更新完成：实际 {done_items} 项，预估 {estimated} 项（预估公式待校准）"
                    )
                # 「每次下载第一人称 mod 时都要改」（用户 2026-10-04）：这一整轮装完，
                # 立刻把第一人称的 `[endfield-enhancer]`（中文 + 与 EFMI 共存必需项）
                # 与中文字体写进**生效那份** ReShade.ini —— 用户装完组件常常直接进游戏，
                # 不走一键启动。幂等；失败只记一行日志，不影响"已完成 N 项"的结论。
                try:
                    synced = self._sync_firstperson_ini_after_install()
                    if synced.get("enhancer") or synced.get("style") or synced.get("created"):
                        self._dep_task["log"].append(
                            "第一人称设置已写入生效那份 ReShade.ini"
                            f"（{synced.get('enhancer', 0)} 项 + 字体 {synced.get('style', 0)} 项）"
                        )
                except Exception as exc:  # noqa: BLE001
                    self._dep_task["log"].append(f"第一人称设置同步失败（忽略）: {exc}")
            except Exception as exc:  # noqa: BLE001
                self._dep_task["message"] = f"失败: {exc}"
                self._dep_task["log"].append(f"失败: {exc}")
            finally:
                self._dep_task["running"] = False

        threading.Thread(target=worker, name="mc-full-update", daemon=True).start()
        return self.get_dependency_progress()

    def pending_component_updates(self) -> dict[str, Any]:
        """**读随包版本表**，给出「有哪些组件该更新了」——纯本地，不联网。

        用户 2026-10-03：「那个一键启动检查更新**还是要加**，但是是**随包资源里配一张
        版本表**，每次比对那个表，然后**随管理器更新而更新**，对旧版本**没有这个表，
        如果表不存在就跳过**」。

        为什么不用联网版（`check_component_updates`）：那次实测要 **6.1 秒**
        （GitHub 的 XXMI/Libs/EFMI + reshade.me + 乳摇 + Poser），
        放在"一键启动前"就是"点一下干等 6 秒"——用户明确说过「反应很慢」。
        读表是微秒级，所以可以放心放在启动路径上。

        **表不存在**（旧版本 exe 没有这个文件）⇒ 返回空列表 ⇒ 前端直接跳过。
        """
        from . import component_versions

        installed: dict[str, str] = {}
        # 内置组件：读各自的 marker
        try:
            from . import runtime_deps

            root = self.config.builtin_runtime_path / "XXMI"
            marker = runtime_deps._read_marker(root) or {}
            installed["XXMI"] = str(marker.get("version") or "")
            installed["XXMI-Libs"] = str(marker.get("XXMI-Libs_version") or "")
            installed["EFMI"] = str(marker.get("EFMI_version") or "")
            # Poser 的版本另存（与上面同一处的写法保持一致）
            try:
                from . import poser

                installed["Poser"] = str(poser.installed_version(self.config) or "")
            except Exception:            # noqa: BLE001
                pass
        except Exception as exc:         # noqa: BLE001
            launcher._append_log(self.config, f"版本表比对：读内置组件版本失败（{exc}）")
        # 外部组件：复用现成的 component_versions()
        try:
            from . import updates

            versions = updates.component_versions(self.config)
            for key in ("reshade", "secondary_motion"):
                row = versions.get(key) or {}
                installed[key] = str(row.get("version") or "")
        except Exception as exc:         # noqa: BLE001
            launcher._append_log(self.config, f"版本表比对：读外部组件版本失败（{exc}）")

        outdated = component_versions.outdated(installed)
        if outdated:
            launcher._append_log(
                self.config,
                "版本表比对：" + "、".join(
                    f"{o['key']} {o['current']}→{o['latest']}" for o in outdated))
        return {"ok": True, "outdated": outdated, "installed": installed}

    def get_dependency_progress(self) -> dict[str, Any]:
        if self._dep_task is None:
            # ⚠️ 2026-10-04：**没有依赖任务时也要给速度**。一键启动 / 「安装内置组件」
            # 这些路径不经过 `_dep_task`（它们直接在 launcher / runtime_deps 里跑），
            # 但下载确实在发生 —— 速度由 `fastnet` 全局采样。不给的话用户看到的就是
            # 「进度条在动、速度卡一直横线」（2026-10-04 用户原话）。
            from . import fastnet as _fastnet

            return {"running": False, "current": 0, "total": 0, "percent": 0.0, "message": "未开始",
                    "log": [], "results": [], "speed_bps": _fastnet.global_speed(),
                    "bytes_received": 0}
        snapshot = dict(self._dep_task)
        # 速度只在"刚刚还在下载"时有效：下载之间的空档（解压 / 安装 / 校验）超过 3 秒就报 0，
        # 否则卡片会一直挂着一个早就不动的速度值，看着像卡住了。
        import time as _t

        sampled_at = snapshot.get("_speed_at")
        if not snapshot.get("running") or not sampled_at or (_t.time() - float(sampled_at)) > 3.0:
            snapshot["speed_bps"] = 0.0
        if float(snapshot.get("speed_bps") or 0.0) <= 0:
            # 本任务的采样还没到（例如走的是 `progress=` 而不是 `byte_progress=` 的那条路）
            # ⇒ 用全局采样兜底 —— 同一次下载，别让界面显示成"没有速度"
            from . import fastnet as _fastnet

            snapshot["speed_bps"] = _fastnet.global_speed()
        snapshot.pop("_speed_bytes", None)
        snapshot.pop("_speed_at", None)
        return snapshot

    def read_launch_log(self, tail: int = 300) -> dict[str, Any]:
        paths = [self.config.runtime_path / "launch.log"]
        loader = self.config.migoto_loader_path
        if loader is not None:
            paths.append(Path(loader).parent / "endfieldmodcontroller.addon.log")
        game_dir = reshade_integration.detect_game_dir(self.config)
        if game_dir is not None:
            paths.append(game_dir / "endfieldmodcontroller.addon.log")
        lines: list[str] = []
        for path in paths:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            if path.name != "launch.log":
                lines.append(f"===== {path} =====")
            lines.extend(content)
        # tail 直接来自前端：传 None/字符串会让 int() 抛异常、日志页整个打不开。
        try:
            count = max(1, min(int(tail or 300), 5000))
        except (TypeError, ValueError):
            count = 300
        return {"ok": True, "text": "\n".join(lines[-count:])}

    def clear_launch_log(self) -> dict[str, Any]:
        removed = diagnostics.clear_logs(self.config)
        loader = self.config.migoto_loader_path
        if loader is not None:
            addon_log = Path(loader).parent / "endfieldmodcontroller.addon.log"
            try:
                if addon_log.is_file():
                    addon_log.unlink()
                    removed.append(str(addon_log))
            except OSError:
                pass
        game_dir = reshade_integration.detect_game_dir(self.config)
        if game_dir is not None:
            addon_log = game_dir / "endfieldmodcontroller.addon.log"
            try:
                if addon_log.is_file():
                    addon_log.unlink()
                    removed.append(str(addon_log))
            except OSError:
                pass
        return {"ok": True, "removed": removed}

    def read_diagnostic_log(self, tail: int = 800) -> dict[str, Any]:
        return {"ok": True, "text": diagnostics.read_diagnostic_log(self.config, tail)}

    def export_diagnostics(self) -> dict[str, Any]:
        try:
            path = diagnostics.create_diagnostic_bundle(self.config, game_dir=reshade_integration.detect_game_dir(self.config))
            launcher._append_log(self.config, f"诊断包已导出: {path}")
            return {"ok": True, "path": str(path)}
        except Exception as exc:  # noqa: BLE001
            diagnostics.log_exception(self.config, "导出诊断包失败", exc, category="diag")
            return {"ok": False, "message": str(exc)}

    def clear_all_logs(self) -> dict[str, Any]:
        removed = diagnostics.clear_logs(self.config)
        return {"ok": True, "removed": removed}

    # ------------------------------------------------------------------
    # launch
    # ------------------------------------------------------------------
    def download_reshade(self, version: str = reshade.DEFAULT_VERSION) -> dict[str, Any]:
        result = reshade.download_reshade(self.config.reshade_runtime_path, version)
        if not self.config.reshade_dll:
            self.config.reshade_dll = self.config.store_path(result["dll"])
            self.config.save()
        return result

    def check_integrity(self) -> dict[str, Any]:
        return integrity.check_integrity(self.config)

    def repair_integrity(self) -> dict[str, Any]:
        result = integrity.repair_integrity(
            self.config,
            log=lambda message: launcher._append_log(self.config, f"repair: {message}"),
        )
        launcher.prepare_reshade_runtime(self.config, self.config.controller_dir)
        result["integrity"] = integrity.check_integrity(self.config)
        return result

    def launch_preview(self, start_game: bool = False) -> dict[str, Any]:
        return launcher.launch(self.config, dry_run=True, start_game=start_game)

    def launch(self, start_game: bool = False) -> dict[str, Any]:
        launcher._append_log(self.config, f"launch requested from UI (start_game={start_game})")
        try:
            return launcher.launch(self.config, dry_run=False, start_game=start_game)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"launch failed: {exc}")
            raise

    def launch_game(self) -> dict[str, Any]:
        """Explicitly start the game through XXMI/EFMI (`--nogui --xxmi EFMI`)."""
        launcher._append_log(self.config, "launch_game requested from UI")
        try:
            return launcher.launch(self.config, dry_run=False, start_game=True)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"launch_game failed: {exc}")
            raise

    # ------------------------------------------------------------------
    # small utilities
    # ------------------------------------------------------------------
    def _native_file_dialog(self, directory: bool, title: str = "") -> dict[str, Any]:
        """用 **pywebview 的系统原生对话框**选路径。

        返回 `{"ok": True, "path": …}` / `{"ok": False, "cancelled": True}` /
        `{"ok": False, "message": …}`。

        ⚠️ **为什么统一到这条路**（2026-10-03 用户报「mod 库的浏览点了没反应」）：
        `tkinter` 被 `scripts/build_exe.py` 排除在打包之外（实测 exe 里
        `tkinter`/`_tkinter` 各 0 次）⇒ 任何用 tkinter 的选择框在正式版里**必然失效**。
        原生对话框不依赖 tkinter、也不要新依赖。所有"选路径"的地方都走这里，
        别再各写一套（`choose_mod_backup_dir` 之前已经单独实现过一遍）。
        """
        try:
            import webview  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"当前环境没有 pywebview（{exc}），请直接把路径填进输入框"}
        window = getattr(self, "_window", None)
        if window is None:
            try:
                windows = list(getattr(webview, "windows", []) or [])
                window = windows[0] if windows else None
            except Exception:  # noqa: BLE001
                window = None
        if window is None:
            return {"ok": False, "message": "窗口还没就绪，请直接把路径填进输入框"}
        dialog_type = webview.FOLDER_DIALOG if directory else webview.OPEN_DIALOG
        try:
            try:
                picked = window.create_file_dialog(dialog_type, allow_multiple=False)
            except TypeError:      # 老版本 pywebview 不接受 allow_multiple
                picked = window.create_file_dialog(dialog_type)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"打开选择框失败：{exc}"}
        if not picked:
            return {"ok": False, "cancelled": True, "message": "cancelled"}
        path = picked[0] if isinstance(picked, (list, tuple)) else picked
        if not path:
            return {"ok": False, "cancelled": True, "message": "cancelled"}
        return {"ok": True, "path": str(path)}

    def choose_path(self, directory: bool = False, title: str = "选择路径") -> dict[str, Any]:
        """弹出**系统原生的**选择框，返回用户选中的路径。

        ⚠️ **为什么不用 tkinter**（2026-10-03 用户报「mod 库的浏览点了没反应」）：
        这里原来用 `tkinter.filedialog`，而 `scripts/build_exe.py` 把
        **`tkinter` 放进了排除名单**（`for skip in ("tkinter", "matplotlib", ...)`）
        ⇒ **exe 里没有 tkinter**（实测：二进制里 `tkinter` / `_tkinter` 各出现 0 次）
        ⇒ 这个函数**永远返回 `tkinter unavailable`** ⇒ 界面上就是"点了没反应"。

        现在**优先用 pywebview 自带的原生选择框**（`window.create_file_dialog`）：
        它是系统对话框、不依赖 tkinter、也不用新增任何依赖。
        拿不到 window（源码模式/异常）时**退回 tkinter**；两条都不行才如实报错
        —— 而且这次前端**会把原因弹出来**，不再静默。
        """
        # ── 首选：pywebview 原生对话框（统一走 helper）──────────────────────
        native = self._native_file_dialog(directory, title)
        if native.get("ok") or native.get("cancelled"):
            return native
        # 原生这条路走不通（比如源码模式下没有窗口）→ 记一条日志再退回 tkinter
        launcher._append_log(
            self.config, f"原生选择框不可用（改用 tkinter 兜底）：{native.get('message')}")

        # ── 退回：tkinter（源码模式通常可用）────────────────────────────────
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"选择路径失败：tkinter 也不可用（{exc}）")
            return {"ok": False,
                    "message": ("这个版本里没有可用的文件选择框。"
                                "请直接把路径粘贴到输入框里，或者用「设置」页的"
                                "「打开文件夹」按钮找到目录后复制路径。")}
        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if directory:
                selected = filedialog.askdirectory(title=title)
            else:
                selected = filedialog.askopenfilename(title=title)
            root.destroy()
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"选择路径失败：{exc}")
            return {"ok": False, "message": f"打开选择框失败：{exc}"}
        if not selected:
            return {"ok": False, "message": "cancelled"}
        return {"ok": True, "path": selected}

    def enable_anti_cheat_safe_mode(self) -> dict[str, Any]:
        launcher._append_log(self.config, "anti-cheat safe mode requested from UI")
        try:
            return launcher.enable_anti_cheat_safe_mode(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"anti-cheat safe mode failed: {exc}")
            raise

    def restore_anti_cheat_safe_mode(self) -> dict[str, Any]:
        launcher._append_log(self.config, "restore anti-cheat safe mode requested from UI")
        try:
            return launcher.restore_anti_cheat_safe_mode(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"restore anti-cheat safe mode failed: {exc}")
            raise

    def force_close_game(self) -> dict[str, Any]:
        """Force-kill a hung Endfield/loader process left behind after closing."""
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        killed: list[str] = []
        errors: list[str] = []
        for image in ("Endfield.exe", "migoto_loader2.exe", "loader.exe"):
            try:
                result = subprocess.run(
                    ["taskkill", "/F", "/IM", image, "/T"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                )
                if result.returncode == 0:
                    killed.append(image)
                elif not any(marker in (result.stdout or "") for marker in ("not found", "No tasks", "没有运行", "没有找到", "找不到")):
                    errors.append(f"{image}: {result.stdout.strip() or result.stderr.strip()}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{image}: {exc}")
        launcher._append_log(self.config, f"force_close_game: killed={killed} errors={errors}")
        return {"ok": not errors, "killed": killed, "errors": errors}

    def launch_migoto_loader(self) -> dict[str, Any]:
        """Compatibility entry point: always use the official XXMI GUI now."""
        launcher._append_log(self.config, "custom 3DMigoto loader is disabled; opening official XXMI GUI")
        try:
            return launcher.launch_official_gui(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"official XXMI GUI launch failed: {exc}")
            raise

    def launch_official_gui(self) -> dict[str, Any]:
        """Open the official XXMI Launcher EFMI GUI without custom injection."""
        launcher._append_log(self.config, "official XXMI GUI launch requested from UI")
        try:
            return launcher.launch_official_gui(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"official XXMI GUI launch failed: {exc}")
            raise

    # ------------------------------------------------------------------
    # DLSS5 / 第一人称注入（本方案唯一注入路径）
    # ------------------------------------------------------------------
    def dlss5_status(self) -> dict[str, Any]:
        """当前 XXMI 注入库状态：是否已开、内容是什么、底座文件在不在。"""
        return launcher.dlss5_injection_status(self.config)

    def set_dlss5_injection(self, enabled: bool = True) -> dict[str, Any]:
        """快捷切换：开=注入 d3d12.dll（DLSS5+第一人称+Mod），关=只跑服装 Mod。"""
        launcher._append_log(self.config, f"set_dlss5_injection(enabled={enabled}) requested from UI")
        try:
            return launcher.configure_dlss5_injection(self.config, enabled=bool(enabled))
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"DLSS5 注入开关失败: {exc}")
            raise

    # ------------------------------------------------------------------
    # 乳摇插件（SecondaryMotion，第三方工具，本程序只做集成与启动）
    # ------------------------------------------------------------------
    def secondary_motion_status(self) -> dict[str, Any]:
        from . import secondary_motion

        return secondary_motion.status(self.config)

    def _persist_injection_switch(
        self, key: str, enabled: bool, result: dict[str, Any]
    ) -> dict[str, Any]:
        """把「拨动即装卸」的结果落进配置（2026-10-03 修「这两个开关关不掉」）。

        现象（用户 2026-10-03 实测，日志可查）：点 ShakingBreastManager / Endfield Poser
        的开关，后端**确实**执行了卸载/停用（`runtime\\logs` 里有动作记录），但界面立刻
        又弹回「已开启」，怎么点都关不掉。

        根因：前端拨完开关必然 `refreshState() + loadSettings()`，而 `loadSettings()`
        是**从 config 整份重灌**的 —— 动作做了、配置没写，界面就被旧值覆盖回来。
        更糟的是 `initialize._check_secondary_motion` / `runtime_deps.ensure_poser`
        都按配置决定要不要注入，配置没变 ⇒ 下次一键启动照样装回去。

        **写配置的判据 = 「动作确实发生了」或「明确成功」**：
        * `ok=True`（含"本来就是目标状态、无需改动"这种幂等成功）⇒ 写；
        * `ok=False` 但 `actions` 非空（做了一半，例如"找不到 sbm 注入源"时仍写好了
          管理器配置）⇒ 也写 —— 用户点的就是"开/关"，**他的意愿必须被记下**，
          否则下次自检会按旧配置把它反向做回去；遗留问题由 `message`/`warnings` 告知。
        * 失败且什么都没做（未定位到游戏目录、dll 被游戏占用…）⇒ 一个字都不改，
          前端会把开关拨回原位并弹窗；这里负责把原因补成**人话**（`remove_injection`
          失败时原本只有 `warnings`，界面只能弹「未知原因」）。

        返回里 `{config: {键: 值}}` 是给前端的信号：**出现了就别再把开关拨回去**。
        """
        if not isinstance(result, dict):
            result = {"ok": True}
        warnings = [str(w) for w in (result.get("warnings") or [])]
        ok = result.get("ok", True) is not False
        acted = bool(result.get("actions"))
        if not (ok or acted):
            message = str(result.get("message") or "").strip()
            result["message"] = message or ("；".join(warnings) if warnings else "没能完成这个动作")
            return result
        setattr(self.config, key, bool(enabled))
        try:
            self.config.save()
        except Exception as exc:  # noqa: BLE001 - 动作已生效，写盘失败只作提示
            result["warning"] = f"动作已生效，但写配置失败：{exc}"
        result["config"] = {key: bool(enabled)}
        return result

    def secondary_motion_install(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "补齐乳摇注入 requested from UI")
        result = secondary_motion.ensure_injection(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        return self._persist_injection_switch("secondary_motion_injection", True, result)

    def secondary_motion_uninstall(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "卸载乳摇注入 requested from UI")
        result = secondary_motion.remove_injection(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        return self._persist_injection_switch("secondary_motion_injection", False, result)

    def launch_secondary_motion(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "启动乳摇管理器 requested from UI")
        return secondary_motion.launch_manager(self.config)

    # ------------------------------------------------------------------
    # Endfield Poser（摆姿 / MMD 播放插件，第三方工具，本程序只做集成）
    #   上游 AGPL-3.0：我们只下载它的官方安装包并调用它自己的安装向导，
    #   不随包分发其二进制；摆姿与播放仍然用它自己的面板 / 摆姿页。
    # ------------------------------------------------------------------
    def poser_status(self) -> dict[str, Any]:
        from . import poser

        return poser.status(self.config)

    def poser_install(self) -> dict[str, Any]:
        """装/修：安装包不在位才去取，然后在位就交给它自己的向导补游戏目录里的文件。

        ⚠️ **2026-10-03 第二次修（用户：「mmd 的 Mod 的开关关了之后再点就打不开了」）**：

        * 第一次修的是"开关守卫拦住显式指令" —— `runtime_deps.ensure_poser` 有一道
          「开关关着就跳过」的守卫（那是给**一键启动**用的，免得用户关掉后下次启动又装回来），
          而用户**亲手点**开关打开时也被它拦住，只回一句「用户已关闭「摆姿 / MMD 播放」开关」。
        * 但当时改成了无条件 `force=True`，**副作用是每点一次"开"都要重新下载整个安装包**
          （`ensure_poser` 的 `up_to_date` 短路带 `not force`）—— 网络一慢/一断，开关就还是
          "打不开"，而用户其实**本地早就装好了**。

        所以正确的语义是分开的：
          * **本地安装包已在位** ⇒ 一个字节都不下，直接进 `ensure_injection`（它会自己按
            `_payload_present` 判断、缺文件才跑上游向导）；
          * **本地没有** ⇒ 才去下载，这时必须 `force=True` 绕开开关守卫（用户是显式点击）。
        "要不要**更新**到最新版"是依赖页那个入口的事（那里才是 force 全量检查）。
        """
        from . import poser

        launcher._append_log(self.config, "安装/修复 Endfield Poser requested from UI")
        log = lambda message: launcher._append_log(self.config, message)  # noqa: E731
        pack: dict[str, Any] | None = None
        if not poser.status(self.config, include_web=False).get("pack_ready"):
            pack = poser.ensure_pack(self.config, log=log, force=True)
        else:
            launcher._append_log(self.config, "Poser 安装包已在位 → 不下载，直接补游戏目录里的文件")
        if pack is not None and not pack.get("ok") and not pack.get("status"):
            return pack            # 本地没有、下载也失败 ⇒ 如实报错，别再往下走
        result = poser.ensure_injection(self.config, log=log)
        if pack is not None:
            result["pack"] = pack
        return result

    def poser_uninstall(self) -> dict[str, Any]:
        from . import poser

        launcher._append_log(self.config, "卸载 Endfield Poser requested from UI")
        return poser.remove_injection(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )

    def set_poser_enabled(self, enabled: bool = True) -> dict[str, Any]:
        """开关落地：重命名 `plugin\\poser.dll`（可逆、不动 proxy、不动其它插件）。

        ⚠️ 用户 2026-10-03：「这两个按钮关不掉」—— 与乳摇同一根因：动作做了但
        `poser_injection` 没写，前端 `loadSettings()` 一重灌就弹回「已开启」。
        统一走 `_persist_injection_switch` 落配置。
        """
        from . import poser

        launcher._append_log(self.config, f"Endfield Poser 开关 → {bool(enabled)} requested from UI")
        result = poser.set_enabled(
            self.config, bool(enabled), log=lambda message: launcher._append_log(self.config, message)
        )
        return self._persist_injection_switch("poser_injection", bool(enabled), result)

    def open_poser_web_ui(self) -> dict[str, Any]:
        """打开它自带的摆姿页（http://127.0.0.1:18923）——只读状态，不代它下写操作。"""
        from . import poser

        launcher._append_log(self.config, "打开 Poser 摆姿页 requested from UI")
        return poser.open_web_ui(self.config)

    def poser_log_tail(self, lines: int = 40) -> dict[str, Any]:
        """给界面的「打开 Poser 日志」用：读游戏目录里的 plugin\\poser_log.txt。"""
        from . import poser

        game = poser.game_dir(self.config)
        if game is None:
            return {"ok": False, "message": "未定位到游戏目录", "lines": [], "path": ""}
        path = game / "plugin" / poser.LOG_NAME
        if not path.is_file():
            return {"ok": False, "message": "还没有 Poser 日志（进过一次游戏才会有）",
                    "lines": [], "path": str(path)}
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            return {"ok": False, "message": f"读取失败: {exc}", "lines": [], "path": str(path)}
        return {"ok": True, "path": str(path), "lines": content[-max(1, int(lines)):], "message": ""}

    # ------------------------------------------------------------------
    # Mod 修复 / 回滚 / 移出库（**实验性**）
    #   工具来源：B站 up 主「可可HXL」《终末地Mod修复工具包》v1.5
    #   （`Endfield_PS-T_DrawSection_Fix_v2.1.exe`，随包分发，见 modfix.py 顶部说明）
    #   约定：一律"先整份备份再动手"，并提供一键回滚；删除只是移出库（进回收区）。
    # ------------------------------------------------------------------
    def modfix_status(self) -> dict[str, Any]:
        from . import modfix

        return {"tool": modfix.tool_status(self.config)}

    def sbm_data_status(self) -> dict[str, Any]:
        """乳摇（SBM）角色参数现状：本地几个角色、来源是谁、上次检查补了什么。

        用户 2026-10-01 要求「在作者改之前，mod 管理器自行拉取新的参数文件」——
        这条接口给界面/排查用（真实拉取在后台预热线程里，24 小时节流）。
        """
        from . import sbm_data_sync

        return sbm_data_sync.status(self.config)

    def mod_more_info(self, mod_id: str) -> dict[str, Any]:
        """「更多」菜单要显示的信息：修过没、能不能回滚、修复工具在不在。"""
        from . import modfix

        mod = next((m for m in self._mods() if m.id == mod_id), None)
        if mod is None:
            return {"ok": False, "message": "找不到这个 Mod（可能已被移出库，刷新一下）"}
        state = modfix.is_fixed(mod.path)
        backups = modfix.list_backups(self.config, mod_id)
        return {
            "ok": True, "id": mod_id, "name": mod.name,
            "fixed": state["fixed"], "fixed_files": state["files"],
            "can_rollback": bool(backups), "backup_count": len(backups),
            "last_backup": str(backups[0].get("at_text") or "") if backups else "",
            "tool": modfix.tool_status(self.config),
        }

    def fix_mod(self, mod_id: str) -> dict[str, Any]:
        """修复一个 Mod：临时目录里跑工具（先整份备份，可回滚）。"""
        from . import modfix

        mod = next((m for m in self._mods() if m.id == mod_id), None)
        if mod is None:
            return {"ok": False, "message": "找不到这个 Mod"}
        launcher._append_log(self.config, f"修复 Mod（实验性）: {mod.name}")
        result = modfix.fix_mod(
            self.config, mod.id, mod.path,
            log=lambda message: launcher._append_log(self.config, message),
        )
        self._invalidate_mods()
        return result

    def rollback_mod(self, mod_id: str) -> dict[str, Any]:
        """一键回滚：用最近一次修复前的备份把这个 Mod 还原回去。"""
        from . import modfix

        launcher._append_log(self.config, f"回滚 Mod 修复: {mod_id}")
        result = modfix.rollback_mod(
            self.config, mod_id,
            log=lambda message: launcher._append_log(self.config, message),
        )
        self._invalidate_mods()
        return result

    def delete_mod(self, mod_id: str) -> dict[str, Any]:
        """把 Mod 移出库（进 `runtime\\backups\\mod-trash`，可手动找回），并从勾选里去掉。"""
        from . import modfix

        mod = next((m for m in self._mods() if m.id == mod_id), None)
        if mod is None:
            return {"ok": False, "message": "找不到这个 Mod"}
        launcher._append_log(self.config, f"移出 Mod 库: {mod.name}")
        result = modfix.delete_mod(
            self.config, mod.path,
            log=lambda message: launcher._append_log(self.config, message),
        )
        if result.get("ok"):
            try:
                selected = list(self.config.selected_mods or [])
                if mod_id in selected:
                    self.config.selected_mods = [x for x in selected if x != mod_id]
                    self.config.save()
            except OSError:
                pass
        self._invalidate_mods()
        return result

    def fix_all_mods(self, only_unfixed: bool = True) -> dict[str, Any]:
        """一键修复所有：**后台线程**逐个修（每个都走同一套隔离流程），可轮询进度。

        同步跑会让 pywebview 的界面卡住（29 个 Mod × 复制+跑工具），所以放后台，
        前端用 `fix_all_progress()` 轮询。
        """
        from . import modfix

        mods = [m for m in self._mods() if not m.is_dependency and m.kind in {"character", "unknown"}]
        task = getattr(self, "_modfix_task", None)
        if task is None:
            task = {"running": False, "current": 0, "total": 0, "name": "",
                    "results": [], "message": "", "ok": None}
            self._modfix_task = task
        if task.get("running"):
            return {"ok": True, "already": True, "message": "已经在修了", **task}
        if not mods:
            return {"ok": True, "started": False, "total": 0, "message": "库里没有可修复的 Mod"}

        task.update({"running": True, "current": 0, "total": len(mods), "name": "",
                     "results": [], "message": "开始修复…", "ok": None})
        launcher._append_log(self.config, f"一键修复所有 Mod（实验性）: {len(mods)} 个")

        def worker() -> None:
            def progress(index: int, total: int, name: str) -> None:
                task.update({"current": index, "total": total, "name": name})

            try:
                result = modfix.fix_all(
                    self.config, mods,
                    log=lambda message: launcher._append_log(self.config, message),
                    progress=progress, skip_if_fixed=only_unfixed,
                )
                task["results"] = result.get("results") or []
                task["message"] = str(result.get("message") or "")
                task["ok"] = bool(result.get("ok"))
            except Exception as exc:  # noqa: BLE001
                task["message"] = f"失败: {exc}"
                task["ok"] = False
            finally:
                task["running"] = False
                task["current"] = task.get("total", 0)
                self._invalidate_mods()

        threading.Thread(target=worker, name="emc-modfix", daemon=True).start()
        return {"ok": True, "started": True, "total": len(mods),
                "message": f"已开始修复 {len(mods)} 个 Mod（后台进行，可继续用界面）"}

    def fix_all_progress(self) -> dict[str, Any]:
        """一键修复的进度（前端轮询）。"""
        task = getattr(self, "_modfix_task", None) or {}
        return dict(task)

    # ------------------------------------------------------------------
    # 初始化自检（一键启动时自动跑，也可手动触发）
    # ------------------------------------------------------------------
    def xxmi_running(self) -> dict[str, Any]:
        """XXMI Launcher 是否还在运行？

        前端用它等「XXMI 拉起终末地之后自动关闭」—— 用户要求把首次启动的提示**挪到
        XXMI 关闭之后**再弹（原话：「之前说 xxmi 拉起的时候出的那个弹窗改成 xxmi 关闭
        后出，xxmi 会在拉起终末地后自动关闭」）。那一刻游戏到底起没起来已经能看出来，
        提示才有意义。
        """
        path = self.config.xxmi_launcher_path
        if path is None:
            return {"running": False, "reason": "未配置 XXMI Launcher"}
        try:
            pids = launcher._image_pids(Path(str(path)).name)
        except Exception as exc:  # noqa: BLE001
            return {"running": False, "reason": str(exc)}
        return {"running": bool(pids), "count": len(pids)}

    def game_running(self) -> dict[str, Any]:
        """终末地（Endfield.exe）现在在不在跑。

        前端在 XXMI 退出之后用它判断"游戏到底起没起来" —— 用户要求：
        「可以在 xxmi 退出后检测终末地状态，如果在拉起后 10s 内退出就弹弹窗」。
        """
        pids: set[int] = set()
        for name in ("Endfield.exe", "Endfield"):
            try:
                pids |= launcher._image_pids(name)
            except Exception:  # noqa: BLE001
                continue
        return {"running": bool(pids), "count": len(pids)}

    def prepare_launch(self) -> dict[str, Any]:
        """一键启动前真正要跑的东西：收编手动 Mod + 同步 XXMI 注入库 + 完整初始化自检。

        必须用 launcher.ensure_injections（它内部会调 configure_dlss5_injection 写注入库
        并同步签名），而不是 initialize.ensure_all —— 后者只管文件层，**不写注入库**。
        """
        launcher._append_log(self.config, "prepare_launch requested from UI")
        synced = self.import_manual_mods()
        # 一键启动里**顺带一键更新**（用户要求）：
        #   ① 随包资产缺失 → 就地展开（离线、秒级）
        #   ② 在线组件只补**缺失**的，已就位就完全跳过（不联网、不拖慢启动）
        #   ③ 只有显式打开 auto_update_dependencies 才在启动前一并升级到最新
        component_update = self._ensure_components_for_launch()
        report = launcher.ensure_injections(self.config)
        return {
            "ok": report.get("ok", True),
            "actions": report.get("actions", []),
            "warnings": report.get("warnings", []),
            "initialize": report.get("initialize", {}),
            "injection": launcher.dlss5_injection_status(self.config),
            "manual_mods": synced,
            "component_update": component_update,
            # 第一次启动为 True（本次临时拉起 XXMI 生成过配置）→ UI 在拉起 XXMI 之后
            # 弹「再次启动 / 先不启动」
            "xxmi_bootstrapped": bool(report.get("xxmi_bootstrapped", False)),
        }

    def hot_reload(self) -> dict[str, Any]:
        """**游戏正在运行时**的热重载：改配置 + 发 F10，不用重启游戏。

        用户 2026-10-04 原话：「加一个热重载，如果终末地在运行，现在一键启动那个位置左右切成
        两个按钮，左边一键启动，右边热重载，点了热重载能包括改配置按 f10 等等」。

        做两件事：
          ① **改配置** —— 直接复用 `prepare_launch()`（收编手动 Mod + 同步 XXMI 注入库 + 初始化自检），
             与「一键启动」改的是同一套东西，**不另造一份判据**；
          ② **发 F10** —— `hot_reload.send_f10()`：3DMigoto 收到后才会重新加载配置 / 重扫 Mod
             （机制与两条硬约束见该模块的模块级说明：必须 SendInput、必须游戏在前台）。

        游戏没在跑就直接回明确原因、**不做任何动作** —— 免得用户以为"点了没反应"。
        """
        if not bool(self.game_running().get("running")):
            return {"ok": False,
                    "message": "终末地当前没有运行 —— 先点「一键启动」；热重载只对运行中的游戏生效"}
        launcher._append_log(self.config, "热重载 requested from UI")

        def log(message: str) -> None:
            launcher._append_log(self.config, message)

        # ① **先按当前勾选重建 staging**（2026-10-04 补，这是"运行中切换 Mod 能不能生效"的关键）：
        #    前端勾选/取消勾选 Mod 只走 `save_config`（改 `selected_mods`），真正把 Mod 铺进
        #    `Mods\` 的是 `activation.stage_and_prepare`，而它只在 `_prune_missing_selection()`
        #    里被调用 —— 那条路**只有一键启动/完整性检查会走**。所以热重载以前**根本没动 `Mods\`**，
        #    用户「关掉一个、打开一个、点热重载」在游戏里自然看不出任何变化
        #    （用户 2026-10-04 原话：「就是能在终末地运行的时候，我切换 Mod，比如关掉一个，
        #      打开一个，然后点热重载，能在游戏生效」）。
        try:
            self._prune_missing_selection()
        except Exception as exc:  # noqa: BLE001 - 重铺失败不该拦住后面的重载
            log(f"热重载: 重铺 staging 失败（继续尝试重载）: {exc}")

        try:
            prepared: dict[str, Any] = self.prepare_launch()
        except Exception as exc:  # noqa: BLE001 - 改配置失败也要继续试着发 F10，并如实报告
            log(f"热重载: 改配置失败（仍会尝试发 F10）: {exc}")
            prepared = {"ok": False, "message": str(exc)}
        sent = hot_reload.send_f10(self.config, log=log)
        if sent.get("ok"):
            message = f"已热重载：配置已重铺 + 已向 {sent.get('window')!r} 发送 F10"
        else:
            message = str(sent.get("message") or "热重载失败")
        launcher._append_log(self.config, f"热重载结果: {message}")
        return {"ok": bool(sent.get("ok")), "message": message,
                "prepare": prepared, "f10": sent}

    def _ensure_components_for_launch(self) -> dict[str, Any]:
        """启动前的组件自愈：先补随包资产，再补缺失的在线组件。"""
        def log(message: str) -> None:
            launcher._append_log(self.config, message)

        result: dict[str, Any] = {"assets": [], "components": [], "errors": []}
        try:
            for item in runtime_assets.ensure_all(self.config, log=log):
                result["assets"].append({
                    "name": item.name, "group": item.group,
                    "status": item.status, "message": item.message,
                })
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"随包资产: {exc}")
        try:
            upgrade = bool(getattr(self.config, "auto_update_dependencies", False))
            for item in dlss5_fetcher.ensure_all(self.config, log=log, only_missing=not upgrade):
                result["components"].append({
                    "key": item.get("key", ""),
                    "status": item.get("status", ""),
                    "message": item.get("message", ""),
                })
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"在线组件: {exc}")
        return result

    def _import_archive_file(self, archive_path: Path, name: str) -> dict[str, Any]:
        """把**已经落盘**的压缩包解压进 Mod 库，然后复用收编 + 角色归属流程。

        `import_mod_archive`（小包一次性传）与 `import_mod_finish`（大包分块传）
        都走这里，保证两条路径行为一致。

        支持 `.zip` / `.7z` / `.rar`（用户 2026-10-01 要求「增加支持拖入 7z」「rar 也要」）：
        zip 用标准库（自带 zip-slip 防护），7z/rar 交给 `dependencies.extract_archive`
        （7-Zip 优先，Windows 自带 bsdtar 兜底）。
        """
        import re
        import shutil

        suffix = Path(name).suffix.lower()
        launcher._append_log(self.config, f"导入: 开始解压 {name}（{archive_path.stat().st_size} B）")
        # ⚠️ **解压前先验完整性**（2026-10-03 补）。
        # 用户实测报过 `解压失败：Bad CRC-32 for file 'Female Images + Dark Mode/…/Endmin_HandOnCheek.dds'`
        # —— CRC-32 是 zip 给每个文件存的校验和，对不上说明**内容在传输/写入时坏了**
        #（不是 Mod 的问题、也不是解压器的错）。原来的体验是"解压到一半才炸"，
        # 用户看到一句 `BadZipFile` 不知道该重下还是该换包。
        # 现在先跑一次检查，坏了就明确说"传输过程中坏了、建议重新下载"。
        try:
            from . import archive_check

            verdict = archive_check.verify_archive(
                archive_path,
                warn=lambda message: launcher._append_log(self.config, message),
            )
            if not verdict.get("ok"):
                launcher._append_log(
                    self.config, f"导入: {name} 完整性检查未通过（{verdict.get('kind')}）")
                # ⚠️ **必须给出"文件在哪、要解压到哪"**（2026-10-03 用户要求：
                # 「解压失败弹窗应该给出文件地址和目标地址，让用户自行解压放进去，
                #  **下载的解压也是**」）。用户拿到一个坏包时，最有用的不是"失败了"，
                # 而是**这两个路径** —— 他可以自己去别处下/修，然后手动放进去。
                # 把包**搬到用户能找到的地方**（临时目录会被 finally 清掉，
                # 直接给它的路径等于给一个马上失效的地址）
                kept = _keep_failed_import(self.config, archive_path, name)
                return {"ok": False, "integrity": verdict.get("kind"),
                        "source_path": str(kept),
                        "target_dir": str(self.config.library_path),
                        "message": _manual_extract_hint(
                            verdict.get("message") or "压缩包损坏，请重新下载",
                            kept, self.config.library_path)}
        except Exception as exc:  # noqa: BLE001 —— 检查本身出问题不该挡住导入
            launcher._append_log(self.config, f"导入: 完整性检查出错（忽略继续）：{exc}")
        base = re.sub(r'[\\/:*?"<>|]', "_", Path(name).stem).strip() or "imported_mod"
        dest = self.config.library_path / base
        counter = 1
        while dest.exists():
            counter += 1
            dest = self.config.library_path / f"{base}_{counter}"
        # ⚠️⚠️ **解压前先处理"长路径"**（issue #12：「mod无法解压」；实测那条路径 264 字符，
        # 超过 Windows 上限 259 ⇒ 父目录建得出、文件写不进 ⇒ `[Errno 2] No such file or directory`）。
        # 不做这一步的话，解到一半才抛英文 errno，用户既不知道原因也不知道怎么办。
        _extracted = False
        if suffix == ".zip":
            try:
                from . import longpath as _lp

                import zipfile as _zf

                with _zf.ZipFile(archive_path) as _arc:
                    _verdict = _lp.check_lengths(dest, _arc.namelist())
                if _verdict.get("too_long"):
                    launcher._append_log(
                        self.config,
                        f"导入: {name} 有 {len(_verdict['too_long'])} 个条目路径过长"
                        f"（最长 {_verdict['worst']}，上限 {_verdict['limit']}）—— 先试长路径解压")
                    dest.mkdir(parents=True, exist_ok=True)
                    _extracted = self._extract_zip_into_long(archive_path, dest)
                    if not _extracted:
                        kept = _keep_failed_import(self.config, archive_path, name)
                        return {"ok": False, "long_path": True,
                                "source_path": str(kept),
                                "target_dir": str(self.config.library_path),
                                "message": _lp.explain(dest, _verdict)}
                    launcher._append_log(self.config, "导入: 长路径解压成功")
            except Exception as exc:  # noqa: BLE001 —— 预判本身出错不该挡住导入
                launcher._append_log(self.config, f"导入: 长路径预判出错（按常规继续）：{exc}")
                _extracted = False

        try:
            dest.mkdir(parents=True, exist_ok=True)
            if _extracted:
                pass                                  # 上面已经用扩展前缀解好了
            elif suffix == ".zip":
                self._extract_zip_into(archive_path, dest)
            else:
                # 7z/rar 在**临时目录**里解，再整份搬进库：这样即使包里有
                # `../` 之类的路径逃逸，也只会落在临时目录里，进不了 Mod 库。
                # tolerate_partial：bsdtar 解部分 rar 时会为个别目录条目返回 exit 1，
                # 而文件其实已经解出来了 —— 那种情况继续导入，把原因写进日志。
                dependencies.extract_archive(
                    archive_path, dest, strip_root=True,
                    warn=lambda message: launcher._append_log(self.config, message),
                    tolerate_partial=True,
                )
        except Exception as exc:  # noqa: BLE001  （BadZipFile / RuntimeError / OSError …）
            launcher._append_log(self.config, f"导入失败（解压）: {exc}")
            shutil.rmtree(dest, ignore_errors=True)
            # ⚠️ 同上面：**给出文件地址与目标地址**，让用户能自己解压放进去
            #（2026-10-03 用户要求：「…让用户自行解压放进去，下载的解压也是」）。
            kept = _keep_failed_import(self.config, archive_path, name)
            return {"ok": False,
                    "source_path": str(kept),
                    "target_dir": str(self.config.library_path),
                    "message": _manual_extract_hint(
                        f"解压失败：{exc}", kept, self.config.library_path)}

        # 很多 Mod 包外面还套了一层同名目录；若里面只有一个子目录且没有文件，把内容提上来，
        # 否则扫描时会把那一层当成 Mod 名、角色也识别不到。
        try:
            children = list(dest.iterdir())
            if len(children) == 1 and children[0].is_dir():
                inner = children[0]
                for item in list(inner.iterdir()):
                    shutil.move(str(item), str(dest / item.name))
                inner.rmdir()
        except OSError:
            pass

        # ⚠️ 2026-10-03 去重：`dest` 带 `_2`/`_3` 后缀 ⇒ 说明库里有同名目录。
        # 旧逻辑"重名就一直加后缀、从不比对内容"，于是同一个包导入两次就在库里躺两份
        # （用户反馈「去重没做好，现在莱万汀那里有两个一样的」，实测那两份 **82 个文件
        # sha256 完全相同**）。这里把刚解压的这份与已有那份比指纹，一样就撤掉刚建的，
        # 按"已经在库里了"返回 —— 只在**同名冲突**时才算指纹，日常导入没有额外开销。
        if counter > 1:
            original = self.config.library_path / base
            try:
                if original.is_dir() and _tree_digest(dest) == _tree_digest(original):
                    shutil.rmtree(dest, ignore_errors=True)
                    launcher._append_log(
                        self.config,
                        f"导入: 「{base}」与库里已有内容完全相同，跳过重复入库（未新增文件）",
                    )
                    return {
                        "ok": True, "duplicate": True, "name": base, "group": "",
                        "dest": str(original),
                        "message": f"「{base}」已经在 Mod 库里了（内容完全相同），这次没有重复添加。",
                    }
            except OSError as exc:
                launcher._append_log(self.config, f"导入: 重复检查失败（照常入库）: {exc}")

        launcher._append_log(self.config, f"导入: 解压完成 → {dest.name}，开始收编与角色识别")
        try:
            synced = self.import_manual_mods()
            # **解压进库的新目录要立刻可见**：`_mods()` 是有缓存的，而"收编"只处理
            # 手动放进游戏 Mods 目录的东西（found 为空时不会失效缓存）。少了这一行，
            # 下面拿到的就是**导入前的旧列表** → 找不到新 Mod → 永远判定"角色已识别"，
            # 于是识别不出角色的包**根本不弹角色确认窗**（2026-10-01 用户反馈的 bug）。
            self._invalidate_mods()
            mods = self._mods()
            # ⚠️ **别用字符串前缀判断"这个 Mod 是不是刚解压的那个"**（2026-10-04 修）：
            # 旧写法 `str(m.path).startswith(str(dest))` 在库里同时存在 `foo` 与 `foo_bar`
            # 时会命中错的那个（`…\foo_bar` 也是 `…\foo` 的前缀），于是"插入了 A、界面却
            # 提示 B 的角色归属"。统一走 `fsutil.is_within`（resolve + is_relative_to）。
            target = next((m for m in mods if fsutil.is_within(dest, m.path)), None)
            pending = self.pending_characters()
            pending_ids = {item.get("id") for item in (pending.get("pending") or [])}
        except Exception as exc:  # noqa: BLE001
            # 收编/识别阶段出问题时**不要**让整个进程崩：把原因写进日志并如实返回
            launcher._append_log(self.config, f"导入: 收编或识别失败（文件已解压到库）: {exc}")
            return {"ok": False, "dest": str(dest),
                    "message": f"已解压到 Mod 库，但收编/识别失败：{exc}"}
        info = None
        if target is not None:
            info = {
                "id": target.id,
                "name": target.name,
                "group": target.group,
                "confidence": target.char_confidence,
                "candidates": list(target.char_candidates),
                "guess": target.char_guess,
            }
        need_confirm = bool(target is not None and target.id in pending_ids)
        # 包里可能压根没有 .ini（比如拖错了文件）—— 那样它不会出现在 Mod 列表里，
        # 必须如实告诉用户，否则界面只会说"已导入"，用户会以为成功了。
        warning = ""
        if target is None:
            warning = "已解压到 Mod 库，但没在里面找到 .ini，可能不是有效的服装 Mod 包"
        launcher._append_log(
            self.config,
            f"导入: 完成 {dest.name}（识别={target.group if target else '未识别'}"
            f"，置信度={target.char_confidence if target else '-'}"
            f"，需确认={'是' if need_confirm else '否'}）")
        return {
            "ok": True,
            "name": dest.name,
            "dest": str(dest),
            "synced": synced,
            "group": (target.group if target is not None else ""),
            "confidence": (target.char_confidence if target is not None else ""),
            "candidates": (list(target.char_candidates) if target is not None else []),
            "need_confirm": need_confirm,
            "mod_id": (target.id if target is not None else ""),
            "warning": warning,
            "imported": info,
            "pending_total": pending.get("total", 0),
        }

    # ── Mod 下载（粘贴网址 → 并行下载 → 自动解压入库）──────────────────────────
    # 用户 2026-10-02 原话：「在 mod 库页按钮下面加一个 mod 下载，**下载进临时文件夹**，
    # **能解压的解压进库**，**不能解压的提示用户需要手动解压**，**并行多线程下载**」；
    # 下载源 = 「**给个输入框输入网址**」⇒ 这里收的就是用户粘贴的 http(s) 直链。
    def start_mod_download(self, urls: Any) -> dict[str, Any]:
        """起一批下载任务：**多任务并行**，每个任务内部再走 fastnet 的并发分块。

        解压/入库复用 `_import_archive_file()`（拖入 zip 那条已验证的链路：zip-slip 校验、
        自动提层、重名加后缀、收编与角色识别），所以"下载进来"和"拖进来"结果一致。
        """
        links = moddl.parse_urls(urls if isinstance(urls, str) else list(urls or []))
        if not links:
            return {"ok": False,
                    "message": "没看到有效的网址 —— 要 http:// 或 https:// 开头的直链，一行一个"}
        with self._mod_dl_lock:
            if not self._mod_dl.get("done", True):
                return {"ok": False, "message": "上一批还在下载中，等它跑完再开新的"}
            self._mod_dl = {
                "cancel": False, "pause": False,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "done": False,
                "dir": str(moddl.downloads_dir(self.config)),
                "items": [
                    {"url": link, "origin_url": link,      # origin_url = 用户粘的那个（香蕉网常是页面地址）
                     "name": moddl.file_name_from(link), "status": "等待中",
                     "percent": 0, "received": 0, "size": 0, "message": "", "path": ""}
                    for link in links
                ],
            }
            items = self._mod_dl["items"]
        launcher._append_log(self.config,
                             f"Mod 下载: 开始 {len(links)} 个任务（并行）→ {moddl.downloads_dir(self.config)}")
        threading.Thread(target=self._mod_download_worker, args=(items,), daemon=True).start()
        return {"ok": True, "total": len(links), "items": items}

    def _mod_download_worker(self, items: list[dict[str, Any]]) -> None:
        """并行下载；**解压入库串行**（同一把锁）—— 文件系统操作串行更稳，
        也避免两个包同时往库里写时"重名加后缀"的判断互相打架。"""
        from concurrent.futures import ThreadPoolExecutor

        dest_dir = moddl.downloads_dir(self.config)
        try:
            with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as pool:
                futures = [pool.submit(self._mod_download_one, item, dest_dir) for item in items]
                for future in futures:
                    future.result()          # 异常已在 _mod_download_one 内部吞掉
                # **封面图一律不留**（用户 2026-10-02：「入库或者中断图片也要删」）——
                # 放在这里统一做，是因为任务有成功/失败/待手动解压三条出路径，逐条加容易漏。
                self._cleanup_download_covers(items)
        finally:
            with self._mod_dl_lock:
                self._mod_dl["done"] = True
                paused = bool(self._mod_dl.get("pause"))
                stopped = bool(self._mod_dl.get("cancel"))
                counts = moddl.summarize(items)
            if paused or stopped:
                # 用户主动停的（2026-10-04 修）：别写成"全部结束" —— 他会以为没停下。
                # 也别把"已经下完并入库的那几个"说成还在跑：如实写"本次入库 N 个，
                # 其余保留断点/已终止"（他实测报过「暂停显示已下载并入库 1 个」的困惑）。
                launcher._append_log(
                    self.config,
                    f"Mod 下载: 已{'暂停' if paused else '终止'}"
                    f"（本次已完成入库 {counts['imported']} 个，"
                    f"{'其余保留断点，点「继续」接着下' if paused else '半成品已清理'}）")
            else:
                launcher._append_log(
                    self.config,
                    f"Mod 下载: 全部结束（入库 {counts['imported']}，需手动解压 {counts['manual']}，"
                    f"失败 {counts['failed']}）")

    @staticmethod
    def _cover_data_uri(path: Any) -> str:
        """把封面图读成 data URI（WebView2 里 `file://` 读不到本地图，只能内联）。

        封面文件**随后就会被收尾清掉**，所以必须在删之前把它转好并留在任务上
        （2026-10-02 踩过：先删文件、后按需转 data URI ⇒ 界面上的封面变空白）。
        """
        import base64 as _base64

        try:
            blob = Path(path).read_bytes()
        except OSError:
            return ""
        if not blob or len(blob) > 400_000:
            return ""
        return "data:image/jpeg;base64," + _base64.b64encode(blob).decode("ascii")

    def _cleanup_download_covers(self, items: list[dict[str, Any]]) -> None:
        """清掉这次下载留在临时目录里的**封面图**。

        用户 2026-10-02：「入库或者中断图片也要删」。封面只用于"下载时先看一眼"，入库时
        已经**拷了一份进 Mod 目录**（`cover.jpg`，Mod 卡片读它），所以临时目录那份不管任务
        是成功、失败还是待手动解压，都不该留着。
        ⚠️ 只删任务自己记下的那个文件路径，不扫目录、不碰别的任务的东西。
        """
        for item in items:
            cover = Path(item.get("cover") or "")
            # **先转成 data URI 再删**：删完文件界面上的封面会变空白（2026-10-02 踩到）
            if item.get("cover") and "cover_data" not in item:
                item["cover_data"] = self._cover_data_uri(cover)
            try:
                if cover.is_file():
                    cover.unlink()
                    item["cover_cleaned"] = True
            except OSError:
                pass

    def _write_source_sidecar(self, mod_dir: Path, item: dict[str, Any]) -> None:
        """把「从哪个页面来的 / 网站分类」写进 `mod.meta.json`（**只补来源类字段**）。

        为什么需要它：`mod.meta.json` 是**程序读的**那份 sidecar —— `core.load_sidecar()`
        读的就是它，而 `ModInfo.source` / `source_id` 一直留着字段却没人写（下载只写了给人看的
        `download-info.json`）。用户 2026-10-04 要求「把 mod 在香蕉网中的分类接入管理器的分类」，
        分类要能被扫描带出来，就得落在这一份里。

        ⚠️⚠️ **绝不碰 `kind` / `group` / `character` 这三个键**：
        `core.infer_kind_and_group()` 只要看到 `meta["kind"]` 有值就**整块跳过自动判据**
        （那句"用户显式指定过"）。在这里写 `kind` 等于把自动识别永久冻住 ——
        那正是"看着接了、其实把判据废了"的做法。这里只补来源类的只读信息。

        写失败不影响入库结果（与 `write_download_info` 同一口径）；**读不动就整体跳过**，
        绝不用空对象覆盖用户已经改过的 sidecar。
        """
        import json as _json

        try:
            directory = Path(str(mod_dir))
            if not directory.is_dir():
                return
            meta_path = directory / "mod.meta.json"
            payload: dict[str, Any] = {}
            if meta_path.is_file():
                try:
                    loaded = _json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    # ⚠️ 文件在、但内容不是合法 JSON —— **绝不能覆盖**：那会把用户手工设过的
                    # 角色/类型整份清掉（比不写这条来源信息严重得多）。
                    launcher._append_log(
                        self.config,
                        "Mod 下载: mod.meta.json 读不动（不是合法 JSON），已跳过来源信息写入（没动它）")
                    return
                if isinstance(loaded, dict):
                    payload = loaded
            if item.get("mod_id"):
                payload.setdefault("id", str(item["mod_id"]))
            name = str(item.get("title") or item.get("name") or "")
            if name:
                payload.setdefault("name", name)
            if item.get("site_category"):
                payload["source"] = "gamebanana"
                payload["source_id"] = str(item.get("site_id") or "")
                payload["source_page"] = str(item.get("page") or "")
                payload["site_category"] = str(item["site_category"])
                payload["site_category_root"] = str(item.get("site_category_root") or "")
            meta_path.write_text(
                _json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:  # noqa: BLE001 —— 写不进去只是少一条元数据
            launcher._append_log(
                self.config, f"Mod 下载: 来源信息没写进 mod.meta.json（{exc}）")

    def _retire_same_source(self, dest_dir: Any, *, source_url: str, file_url: str) -> list[str]:
        """把库里**同一个来源**的旧版移出（进 `mod-trash`，可找回）。

        用户 2026-10-03：「**对于确认下载地址一致的，要在入库的时候移出旧的**」。
        场景：同一份 Mod 重下/换新版后，库里会新旧两份并存（他今天就得手动清）。

        **判据必须"确认一致"**：只认 `download-info.json` 里记的
        `来源网址` / `文件网址` **完全相等**（不猜名字、不比相似度）——
        名字相同但来源不同的两个包（例如作者重发）不该被误伤。
        只动 `library` 里、且**不是刚入库的这个目录**的那些。
        """
        import json as _json
        import shutil as _shutil

        new_dir = Path(str(dest_dir)).resolve() if dest_dir else None
        src = str(source_url or "").strip()
        fil = str(file_url or "").strip()
        if new_dir is None or not (src or fil):
            return []
        trash = self.config.runtime_path / "backups" / "mod-trash"
        retired: list[str] = []
        try:
            candidates = [d for d in self.config.library_path.iterdir() if d.is_dir()]
        except OSError:
            return []
        for folder in candidates:
            try:
                if folder.resolve() == new_dir:
                    continue
            except OSError:
                continue
            info = folder / "download-info.json"
            if not info.is_file():
                continue                      # 没记录来源 ⇒ **不猜**，绝不动它
            try:
                data = _json.loads(info.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            same = ((src and str(data.get("来源网址") or "").strip() == src)
                    or (fil and str(data.get("文件网址") or "").strip() == fil))
            if not same:
                continue
            try:
                trash.mkdir(parents=True, exist_ok=True)
                target = trash / folder.name
                # 重名就加时间戳，绝不覆盖 trash 里已有的东西
                if target.exists():
                    import time as _t

                    target = trash / f"{folder.name}.{_t.strftime('%Y%m%d-%H%M%S')}"
                _shutil.move(str(folder), str(target))
                retired.append(folder.name)
            except OSError as exc:
                launcher._append_log(self.config, f"Mod 下载: 旧版 {folder.name} 移出失败（{exc}）")
        return retired

    def _mod_download_one(self, item: dict[str, Any], dest_dir: Path) -> None:
        url = item["url"]
        item["status"] = "下载中"

        # ⚠️⚠️ **「用户停了吗」这个判据必须在最前面就能用**（2026-10-04 修，用户实测）。
        # 原来 `cancelled()` 定义在真正开始下载之前、也只在下载循环里被检查 ⇒ 用户在
        # **探测阶段**（「读取香蕉网信息」＝ `gamebanana_profile` 请求 + 下封面，各 25 秒超时）
        # 点「暂停」或「终止」**完全没用**，界面上一直停在"探测中"。他的原话：
        #   「mod下载过程中，**探测期间无法暂停**」「点了**终止也还是探测中**」
        # 现在：探测前 / 探测后 / 封面 / 每个配套文件都检查，并把 `cancel=` 传进那两个网络请求。
        def cancelled() -> bool:
            with self._mod_dl_lock:
                return bool(self._mod_dl.get("cancel") or self._mod_dl.get("pause"))

        def finish_cancelled() -> None:
            """被用户停下时统一收尾：状态写「已暂停 / 已终止」+ 说明（**这不是失败**）。"""
            with self._mod_dl_lock:
                stopping = bool(self._mod_dl.get("pause"))
            item["status"] = "已暂停" if stopping else "已终止"
            item["message"] = ("暂停中（点「继续」会从断点接着下）" if stopping
                               else "已终止（半成品已清掉）")

        if cancelled():
            finish_cancelled()
            return
        # ⚠️ **必须在函数开头初始化**（2026-10-03 踩到）：它只在下面的 GameBanana 分支里被赋值，
        # 而普通 URL 直接下载不走那条路 ⇒ 后面读它就成了 `UnboundLocalError`，
        # 整个下载线程静默挂掉、任务永远停在"下载中"（7 个测试一起红了）。
        aux_files: list[dict[str, Any]] = []

        # 速度：滑动窗口（最近 5 秒）算，别用"总字节/总耗时"——那会被开头那段探测拖低，
        # 也别用瞬时值——那会跳。用户 2026-10-02：「下载过程要有进度条显示速度」。
        speed_history: list[tuple[float, int]] = []

        def progress(done: int, total: int) -> None:
            now = time.monotonic()
            item["received"] = int(done)
            item["size"] = int(total or 0)
            item["percent"] = int(done * 100 / total) if total else 0
            item["last_tick"] = time.time()          # 卡死检测用（见 mod_download_progress）
            speed_history.append((now, int(done)))
            while len(speed_history) > 1 and now - speed_history[0][0] > 5:
                speed_history.pop(0)
            span_seconds = now - speed_history[0][0]
            if span_seconds >= 0.5:
                item["speed_bps"] = max(0, int(done - speed_history[0][1])) / span_seconds
        item["last_tick"] = time.time()

        # ── 香蕉网（GameBanana）链接：先把页面元数据换成**真实文件直链**，顺手带一张封面 ──
        # 用户 2026-10-02：「看看能不能看到网址是香蕉网…就拉取资源同时拉取一张图片，
        # 然后如果访问不上，就弹窗提示无法访问，建议检查 vpn」。
        banana_id = moddl.gamebanana_id(url)
        if banana_id is not None:
            from . import fastnet as _fastnet

            item["status"] = "读取香蕉网信息"
            try:
                # 把 cancel 传进去 ⇒ 探测本身也能被「暂停 / 终止」打断（见上面 cancelled() 说明）
                profile = moddl.gamebanana_profile(banana_id, cancel=cancelled)
            except _fastnet.Cancelled:
                finish_cancelled()
                return
            except moddl.GameBananaUnreachable as exc:
                # 这里刻意**不**抛给上层：一个任务失败不该影响同一批里的其它任务
                item["status"] = "失败"
                item["unreachable"] = True
                detail = str(exc)[:120]
                item["message"] = ("访问不上香蕉网（超时 / DNS / 证书 / 地区限制）—— "
                                   "建议检查 VPN 或加速器后重试。" + (f"（{detail}）" if detail else ""))
                launcher._append_log(self.config, f"Mod 下载: 香蕉网 {banana_id} 访问失败：{exc}")
                return
            # 探测拿到结果后**立刻再查一次**：用户可能就是在探测期间点的暂停/终止
            if cancelled():
                finish_cancelled()
                return
            files = profile["files"]
            # ⚠️⚠️ **按更新时间挑主包，并把配套小文件一起下**（2026-10-03 用户实测：
            #     「uimod 好像没生效」）。
            # 原先这里是 `next((entry for entry in files if not archived), files[0])`
            # —— 取"列表第一个未归档的"，而 API 的 `_aFiles` **不是按时间排的**：
            # 那个 Mod 的顺序是 1.3.1(86MB) / _core_2 / _core_ffd68 / 1.8.2(957MB)，
            # 于是下载到了 **1.3.1 旧版**；而真正的 `_Core.ini`（作者单独发的
            # `_core_2.zip`，275 B）**从来没被下载过** —— 主包缺它根本不工作。
            # ⚠️⚠️ **先看"最新版需要下什么"，再决定下哪些**（用户 2026-10-04 要求：
            # 「应该先去 gamebanana.com/mods/updates/<id>，看**最新版需要下什么资源**，
            # 然后再去下载，而不是一上来就下最新的包」）。
            # `required_ids` = 最新那条更新记录的 `_aFileRowIds`（实测 mod 690864 的 1.8.2
            # 给出 [1813631, 1809855] ⇒ `changescreens_182.zip` + `_core_2.zip`）。
            # 没有更新记录（老 Mod / 接口取不到）时才退回"按时间挑最新主包"。
            picked, aux_files = moddl.split_mod_files(files, profile.get("required_ids"))
            if picked is None:
                item["status"] = "失败"
                item["message"] = "这个页面里没有可下载的文件"
                return
            item["title"] = profile["name"]
            item["author"] = profile["author"]
            item["game"] = profile["game"]
            item["page"] = profile.get("page", "")
            # 网站分类（`Skins` / `UI` / `Other/Misc`，Skins 下还带角色名）——
            # 用户 2026-10-04：「把 mod 在香蕉网中的分类接入管理器的分类」。
            # ProfilePage 本来就带这两个字段，所以**这一项不产生任何额外请求**；
            # 先挂在任务项上，入库时写进这个 Mod 自己的 sidecar（见下面 write_download_info）。
            category = profile.get("category") or {}
            if category.get("path"):
                item["site_category"] = str(category["path"])
                item["site_category_root"] = str(category.get("root") or "")
                item["site_id"] = str(banana_id)
            item["version"] = picked.get("version") or profile.get("version") or ""
            item["url"] = picked["url"]              # ← 换成真实下载直链
            item["name"] = picked.get("file") or item.get("name") or ""
            notes = [f"香蕉网：{profile['name']}"]
            if profile["author"]:
                notes.append(f"作者 {profile['author']}")
            if item["version"]:
                notes.append(str(item["version"]))
            latest = profile.get("latest_update") or {}
            if latest:
                # 「按最新更新的资源清单下载」——这是用户 2026-10-04 要的口径。
                label = f"最新更新 v{latest['version']}" if latest.get("version") else "最新更新"
                notes.append(f"按{label}的资源清单下载 {1 + len(aux_files)} 个文件")
                if latest.get("text"):
                    notes.append(f"更新说明：{str(latest['text'])[:120]}")
                if profile.get("required_missing"):
                    notes.append(f"（清单里有 {len(profile['required_missing'])} 个文件已被作者删除，已跳过）")
            elif len(files) > 1:
                notes.append(f"共 {len(files)} 个文件，这个页面没有更新记录，按更新时间取最新主包")
            if aux_files:
                notes.append(f"另有 {len(aux_files)} 个配套文件会一并下载")
            item["note"] = " · ".join(notes)
            if profile["game"] and "endfield" not in profile["game"].lower():
                item["message"] = f"⚠ 这个 Mod 属于「{profile['game']}」，不是终末地的"
            if profile["cover"]:
                # 封面同样是网络请求（25 秒）—— 也要能被打断
                cover = moddl.download_cover(profile["cover"], dest_dir, cancel=cancelled)
                if cover is not None:
                    item["cover"] = str(cover)
            if cancelled():
                finish_cancelled()
                return
            item["status"] = "下载中"
            url = item["url"]

        path, error, slow = moddl.download(
            url, dest_dir, progress=progress, name=item.get("name") or "",
            cancel=cancelled,
            # 暂停要留断点（下次能续），终止不留
            keep_partial=bool(self._mod_dl.get("pause")),
            log=lambda message: launcher._append_log(self.config, message))
        # ⚠️ **配套小文件一并下载**（2026-10-03）：作者单独发的 `_Core.ini` 这类文件
        # 主包缺它根本不工作（实测那个 UI Mod 就是），而它一直没被下载过。
        # 失败**不算主包失败**（主包已经下好了），只记一条日志。
        if path is not None and aux_files:
            for extra in aux_files:
                if cancelled():
                    break
                try:
                    launcher._append_log(
                        self.config, f"Mod 下载: 配套文件 {extra.get('file')}（{extra.get('size')} B）")
                    moddl.download(
                        extra["url"], dest_dir, name=extra.get("file") or "",
                        cancel=cancelled,
                        log=lambda message: launcher._append_log(self.config, message))
                except Exception as exc:  # noqa: BLE001 —— 配套失败不影响主包
                    launcher._append_log(
                        self.config, f"Mod 下载: 配套文件 {extra.get('file')} 失败（已忽略）：{exc}")
        if path is None:
            # 「已暂停」/「已终止」不是失败，如实标出来（用户点的，别报成错误）
            if error in ("已暂停", "已终止"):
                item["status"] = error
                item["message"] = "暂停中（点「继续」会从断点接着下）" if error == "已暂停" else "已终止"
                return
            item["status"] = "失败"
            item["message"] = error or "下载失败"
            # 「慢到被 fastnet 放弃」≠「文件坏了」：前者要提示开 VPN（用户 2026-10-02：
            # 「这么低速明显是没开 vpn，应该弹窗建议开 vpn 而不是纯失败」）
            if slow:
                item["slow"] = True
            return

        item["name"] = path.name
        item["path"] = str(path)
        item["percent"] = 100
        if not moddl.is_extractable(path.name):
            # **不去猜**：非 zip/7z/rar 一律留在临时目录，让用户自己解压（用户 2026-10-02 选的方案）
            #
            # ⚠️ **必须给出"文件在哪、要放到哪"**（2026-10-03 用户：「**下载或拖入解压失败
            # 或不支持没有弹出目标库和文件原位置，让用户手动解压**」—— 这正是那条 issue）。
            # 只写"请手动解压后把文件夹拖进 Mod 库"是不够的：用户不知道**那个文件在哪**、
            # 也**不知道该放到哪个目录**。这里把两个路径都带上，并用同一个 helper 生成
            # 可照做的指引（含一条能直接复制的 tar 命令）。
            item["status"] = "需手动解压"
            item["source_path"] = str(path)
            item["target_dir"] = str(self.config.library_path)
            # 注意措辞：状态叫「需手动解压」，消息里也要出现这四个字（测试与用户搜索都依赖它）
            item["message"] = _manual_extract_hint(
                "需手动解压：这个格式不能自动解压（只支持 "
                + " / ".join(moddl.EXTRACTABLE_SUFFIXES) + "）",
                path, self.config.library_path)
            return

        item["status"] = "解压中"
        try:
            with self._mod_dl_lock:      # 解压 + 入库串行
                result = self._import_archive_file(path, path.name)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "message": f"解压失败：{exc}"}

        if result.get("ok"):
            item["status"] = "已入库"
            item["mod_id"] = result.get("mod_id", "")
            item["group"] = result.get("group", "")
            item["need_confirm"] = bool(result.get("need_confirm"))
            item["message"] = result.get("warning") or result.get("name") or "已解压进 Mod 库"
            # **入库成功后删掉下载目录里的源包**（用户 2026-10-02：「成功入库就删掉」）——
            # 内容已经在 Mod 库里了，留着只是占空间。只删这一次下回来的那个文件（`path` 是
            # download() 返回的、可能已被按内容补过后缀的那个），**绝不碰下载目录里别的东西**；
            # 删不掉也只是留个文件，不影响任务结果。
            try:
                if path.exists():
                    path.unlink()
                    item["source_removed"] = True
                    launcher._append_log(self.config, f"Mod 下载: 已入库，已清理源包 {path.name}")
            except OSError as exc:
                launcher._append_log(self.config, f"Mod 下载: 源包没删掉（{exc}），留着不影响使用")
            # 在这个 Mod **自己的文件夹**里留一份"从哪下的、什么时候下的"
            # （用户 2026-10-02：「还有每个 mod 文件夹内都要保存下载地址、时间这些信息」）
            dest_dir = result.get("dest") or ""
            if dest_dir:
                written = moddl.write_download_info(
                    Path(dest_dir),
                    source_url=item.get("origin_url") or item.get("url") or "",
                    file_url=item.get("url") or "",
                    file_name=item.get("name") or "",
                    title=item.get("title") or "",
                    author=item.get("author") or "",
                    version=item.get("version") or "",
                    game=item.get("game") or "",
                    page=item.get("page") or "",
                    site="GameBanana" if item.get("title") else "",
                    site_category=item.get("site_category") or "",
                )
                if written is not None:
                    item["info_file"] = str(written)
                    launcher._append_log(self.config, f"Mod 下载: 已写入下载信息 {written.name}")
                # 把「从哪个页面来的 / 网站分类」写进**程序读的**那份 sidecar（`mod.meta.json`），
                # 这样扫描时就能带出来（`core.ModInfo.source` / `source_id` / `site_category`）。
                self._write_source_sidecar(Path(dest_dir), item)
                # ⚠️ **同来源的旧版自动移出**（2026-10-03 用户：
                #     「对于确认下载地址一致的，要在入库的时候移出旧的」）。
                # 场景：同一份 Mod 修好后重新下载（或换了新版），库里会同时躺着新旧两份 ——
                # 用户得手动去清，忘了就两个版本混着（他今天正是这样）。
                # 判据 = `download-info.json` 里的**来源网址/文件网址完全一致**（这是"确认一致"），
                # 动作 = 移进 `mod-trash`（**可找回**，不是删除），并如实记日志。
                retired = self._retire_same_source(
                    dest_dir,
                    source_url=item.get("origin_url") or item.get("url") or "",
                    file_url=item.get("url") or "",
                )
                if retired:
                    item["retired"] = retired
                    launcher._append_log(
                        self.config,
                        f"Mod 下载: 同来源的旧版已移出 —— {'、'.join(retired)}（在 runtime\\backups\\mod-trash 可找回）")
                # **把香蕉网的封面存成 Mod 目录里的 `cover.<ext>`** —— 这样 Mod 库卡片就有图了
                # （用户 2026-10-02：「mod库也读不出图片」）。刻意**复用现成通道**而不是另造：
                # `core.find_cover()` 的 COVER_HINTS 里就有 "cover"，命中后前端 `loadCovers()`
                # 会通过 `api.get_mod_cover` 把它读出来。
                cover_source = Path(item.get("cover") or "")
                if cover_source.is_file():
                    try:
                        suffix = cover_source.suffix.lower() or ".jpg"
                        shutil.copyfile(cover_source, Path(dest_dir) / f"cover{suffix}")
                        item["cover_saved"] = True
                    except OSError as exc:
                        launcher._append_log(self.config, f"Mod 下载: 封面没存进库（{exc}）")
        else:
            # ⚠️ **下载侧的解压失败也要给出两个路径**（2026-10-03 用户：
            # 「issue 反馈的应该也是类似问题，**下载或拖入解压失败或不支持没有弹出
            # 目标库和文件原位置**，让用户手动解压」）。
            # `_import_archive_file` 现在会回 `source_path` / `target_dir`，
            # 这里**优先用它给的**（它拿到的 `path` 才是最终落盘的那个、可能已被按内容补过后缀）；
            # 万一没有（旧路径 / 异常兜底），就用本任务自己的 `path` 与 Mod 库补上。
            item["status"] = "需手动解压"
            item["source_path"] = str(result.get("source_path") or path)
            item["target_dir"] = str(result.get("target_dir") or self.config.library_path)
            item["message"] = result.get("message") or _manual_extract_hint(
                "解压失败，请手动处理", path, self.config.library_path)

    def mod_download_progress(self) -> dict[str, Any]:
        """给前端轮询：任务列表 + 计数（下载中/已入库/需手动解压/失败）。

        香蕉网任务的封面图在这里转成 **data URI** 一并给前端 —— WebView2 里 `file://`
        读本地图片会被拦，而缩略图只有几十 KB，直接内联最省事（只转一次，结果缓存在任务上）。
        """
        import base64

        with self._mod_dl_lock:
            items = [dict(item) for item in self._mod_dl.get("items", [])]
            done = bool(self._mod_dl.get("done", True))
            payload = dict(self._mod_dl)
        # 总进度（字节口径）—— 依赖页那个进度条在下载期间就显示它 + 速度
        # （用户 2026-10-02：「下载过程要有进度条显示速度，现在进度条不走，显示 0/0」）。
        # ⚠️ 体积未知的任务（服务器没给 Content-Length）不参与分母，否则百分比会乱跳。
        known_total = sum(int(item.get("size") or 0) for item in items)
        done_bytes = sum(int(item.get("received") or 0) for item in items)
        payload["done_bytes"] = done_bytes
        payload["total_bytes"] = known_total
        payload["speed_bps"] = sum(float(item.get("speed_bps") or 0) for item in items)
        # **「香蕉网高速下载」的状态**（2026-10-03 用户：「香蕉网高速下载逻辑也加进去」）。
        # 前端要能如实说清"现在是不是在并发加速、用了多少条连接"，否则"下载很慢"这件事
        # 用户没法判断是线路问题还是没开加速（他 2026-10-03 问的正是这个）。
        # 数据源：`fastnet` 每次下载都会把报告存进 `_STATE["last"]`（含 `threads` /
        # `boosted` / `reason` / `probe_mbps` / `mbps`）—— 任务字典里没有这些字段。
        try:
            from . import fastnet as _fastnet
            with _fastnet._STATE_LOCK:
                last_report = dict(_fastnet._STATE.get("last") or {})
            payload["policy"] = _fastnet.get_policy()
        except Exception:  # noqa: BLE001
            last_report = {}
            payload["policy"] = ""
        payload["last_report"] = last_report
        payload["threads"] = int(last_report.get("threads") or 0)
        payload["accelerating"] = bool(last_report.get("boosted")) or payload["threads"] > 1
        # **卡死检测**：有任务长时间没有任何数据往来，就判它失败。
        # 用户 2026-10-02 实测遇到"卡片一直显示下载中、进度条 0/0、速度也没有"——
        # 那就是下载线程卡在探测/重试里了，界面必须如实收尾，不能永远挂着"进行中"。
        # 在这里做（前端每秒轮询必然经过）不需要额外线程；只改状态，不强行杀线程。
        now_wall = time.time()
        for item in items:
            if item.get("status") in ("下载中", "解压中") and \
                    now_wall - float(item.get("last_tick") or now_wall) > moddl.MOD_DOWNLOAD_STALL_SECONDS:
                item["status"] = "失败"
                item["message"] = (f"超过 {moddl.MOD_DOWNLOAD_STALL_SECONDS // 60} 分钟没有任何数据往来，"
                                   f"判定为卡死（线路断了 / 站点不通）—— 可重试，或开加速器后重试")
                item["stalled"] = True
                launcher._append_log(
                    self.config,
                    f"Mod 下载: {item.get('name') or item.get('url')} 卡死（长时间无数据），已判失败")
        for item in items:
            if item.get("cover") and "cover_data" not in item:
                item["cover_data"] = self._cover_data_uri(item["cover"])
        counts = moddl.summarize(items)
        return {
            "ok": True, "items": items, "done": done, "counts": counts,
            "dir": payload.get("dir", str(moddl.downloads_dir(self.config))),
            "started_at": payload.get("started_at", ""),
            # ⚠️ 这几个**必须一起返回**（2026-10-03）：上面虽然写进了 `payload`，
            # 但这里 return 的是**重新构造的字典**、没有带上 payload ⇒ 前端永远拿到空值。
            # 它们是「香蕉网高速下载」的状态显示依据（几连接 / 是否在加速 / 当前策略）。
            "done_bytes": payload.get("done_bytes", 0),
            "total_bytes": payload.get("total_bytes", 0),
            "speed_bps": payload.get("speed_bps", 0),
            "policy": payload.get("policy", ""),
            "threads": payload.get("threads", 0),
            "accelerating": payload.get("accelerating", False),
            "last_report": payload.get("last_report", {}),
        }

    def active_download_count(self) -> int:
        """还有几个下载任务在跑（关窗口的原生确认框要显示这个数字）。"""
        with self._mod_dl_lock:
            return sum(1 for item in self._mod_dl.get("items", [])
                       if item.get("status") in ("等待中", "读取香蕉网信息", "下载中", "解压中"))

    def has_active_downloads(self) -> bool:
        """有没有正在跑的下载任务 —— 关窗口前要问一句（用户 2026-10-02 要求）。"""
        return self.active_download_count() > 0

    def confirm_exit(self) -> dict[str, Any]:
        """用户在"正在下载，仍要退出吗"的框里点了"仍然退出"。

        ⚠️⚠️ **必须保证"一定退得掉"**（2026-10-03 用户：「**还有退出弹窗也卡死**」）。
        原先这里是「`self.shutdown()` → `os._exit(0)`」串行执行：
        `shutdown()` 要停下载线程、收尾文件，**它一旦卡住（等锁 / 等线程 / 等网络），
        后面的 `os._exit` 就永远执行不到**，而前端还在 `await` 这个调用的返回 ——
        表现就是"点了仍然退出，然后整个程序卡死"。
        现在：**标记 + 日志立刻做，收尾丢到后台线程且硬限时，主线程直接退出**。
        """
        self.exit_confirmed = True
        try:
            launcher._append_log(self.config, "用户确认在下载中退出程序")
        except Exception:  # noqa: BLE001
            pass

        def _cleanup() -> None:
            try:
                self.shutdown()
            except Exception:  # noqa: BLE001
                pass
            os._exit(0)

        threading.Thread(target=_cleanup, daemon=True).start()
        # 给收尾最多 2 秒；到点无论如何都退（daemon 线程会随进程一起结束）
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
        os._exit(0)

    def cancel_mod_downloads(self) -> dict[str, Any]:
        """**终止**全部下载（用户 2026-10-02：「下载需要终止和暂停按钮」）。

        置标志位，下载线程会在下一个数据块边界停下来（`fastnet.Cancelled`），
        半成品由 `moddl` 清掉 —— 终止就是干干净净地停。
        """
        with self._mod_dl_lock:
            self._mod_dl["cancel"] = True
            self._mod_dl["pause"] = False
        launcher._append_log(self.config, "Mod 下载: 用户点了终止")
        return {"ok": True}

    def pause_mod_downloads(self) -> dict[str, Any]:
        """**暂停**全部下载：停下但**保留断点**，下次「继续」能接着下（fastnet 支持续传）。"""
        with self._mod_dl_lock:
            self._mod_dl["pause"] = True
            self._mod_dl["cancel"] = False
        launcher._append_log(self.config, "Mod 下载: 用户点了暂停（保留断点）")
        return {"ok": True}

    def resume_mod_downloads(self) -> dict[str, Any]:
        """**继续**：清掉暂停标志，并按当前剩余任务重新起一批（断点续传会跳过已下的部分）。"""
        with self._mod_dl_lock:
            self._mod_dl["pause"] = False
            self._mod_dl["cancel"] = False
            pending = [item for item in self._mod_dl.get("items", [])
                       if item.get("status") in ("已暂停", "已终止")]
            if not pending:
                return {"ok": True, "resumed": 0}
            for item in pending:
                item["status"] = "等待中"
                item["message"] = ""
            dir_path = str(self._mod_dl.get("dir") or moddl.downloads_dir(self.config))
            # ⚠️ **必须把 `done` 翻回 False**（2026-10-04 修）：上一批 worker 结束时把它设成了
            # True，而 `start_mod_download` 正是用 `if not self._mod_dl.get("done", True)` 来
            # "上一批还在跑就拒绝开新批次"。继续下载时若不翻回来，用户在这批还没跑完时点
            # 「开始下载」会被放行 → **两个 worker 并发改同一份 `_mod_dl` 状态**（进度乱跳、
            # 完成标志互相覆盖、解压入库的串行假设也被破坏）。
            self._mod_dl["done"] = False
        launcher._append_log(self.config, f"Mod 下载: 继续 {len(pending)} 个任务（断点续传）")
        threading.Thread(target=self._mod_download_worker, args=(pending, Path(dir_path)),
                         daemon=True).start()
        return {"ok": True, "resumed": len(pending)}

    def clear_mod_downloads(self) -> dict[str, Any]:
        """清掉下载任务记录（界面上的「清除记录」按钮）。

        用户 2026-10-02：「这个卡片要去掉」—— 残留的任务行（尤其卡死的那些）得能让用户
        自己扫掉。**有任务正在跑时拒绝**：清记录不能把正在下的东西也抹掉。
        """
        with self._mod_dl_lock:
            active = [item for item in self._mod_dl.get("items", [])
                      if item.get("status") in ("等待中", "读取香蕉网信息", "下载中", "解压中")]
            if active:
                return {"ok": False, "message": f"还有 {len(active)} 个任务在跑，等它们结束再清"}
            self._mod_dl = {"items": [], "done": True, "started_at": "", "dir": ""}
        launcher._append_log(self.config, "Mod 下载: 已清除任务记录")
        return {"ok": True}

    def open_download_dir(self) -> dict[str, Any]:
        """打开下载临时目录（"需手动解压"那条提示旁边的按钮用）。"""
        target = moddl.downloads_dir(self.config)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "message": f"创建下载目录失败：{exc}"}
        return self.open_path(str(target))

    def _extract_zip_into_long(self, archive_path: Path, dest: Path) -> bool:
        r"""用 **Win32 扩展长度前缀（`\\?\`）**把 zip 解进 `dest`，成功返回 True。

        为什么可行：Python 的 `open()` 走 `CreateFileW`，路径带上 `\\?\` 前缀时
        Win32 **跳过 MAX_PATH 检查** ⇒ 超过 260 字符也能写。**进程内生效、不改系统设置**
        （符合"零配置即用"）。逐条解、逐条校验 zip-slip，任何一步失败就整体返回 False，
        由调用方决定怎么告诉用户（不会留下半成品：解之前会先把已写文件清掉）。
        """
        import zipfile

        from . import fsutil
        from . import longpath as lp

        written: list[Path] = []
        try:
            with zipfile.ZipFile(archive_path) as archive:
                for info in archive.infolist():
                    member = info.filename
                    if not member or member.endswith("/"):
                        continue
                    # ⚠️⚠️ **zip-slip 校验必须用"路径语义"而不是字符串前缀**（2026-10-04 修）。
                    # 旧写法 `if not str(dest / member).startswith(str(dest))` 有两个洞：
                    #   ① `..\foobar\x.ini` 拼出来是 `…\dest\..\foobar\x.ini`，**字符串确实
                    #      以 dest 开头** ⇒ 校验通过，而实际写盘时 `..` 被解析 ⇒ 文件落到
                    #      Mod 库**外面**（甚至覆盖库里别的 Mod）；
                    #   ② 库里存在同前缀目录（`foo` 与 `foobar`）时判定也会互相串。
                    # `fsutil.safe_join` 直接拒绝绝对路径 / 盘符 / 任何 `..` 段。
                    target = fsutil.safe_join(dest, member)
                    if target is None:
                        raise ValueError(f"压缩包里有非法路径: {member}")
                    # ⚠️ **每一次文件系统操作都要带扩展前缀**（2026-10-03 实测教训）：
                    # 第一次写的时候只在 `open()` 上加了前缀，而 `mkdir` 用的是普通路径
                    # ⇒ 超长时**父目录建不出来** ⇒ 整个方案失败。
                    # `pathlib` 的 `mkdir` 不会自己加前缀，所以这里显式用 `os.makedirs`。
                    target_ext = lp.extended(target)
                    parent_ext = lp.extended(target.parent)
                    os.makedirs(parent_ext, exist_ok=True)
                    with archive.open(info) as src:
                        with open(target_ext, "wb") as out:
                            while True:
                                chunk = src.read(1 << 20)
                                if not chunk:
                                    break
                                out.write(chunk)
                    written.append(target)
            return True
        except Exception:  # noqa: BLE001 —— 清理半成品后交给调用方报错
            for path in reversed(written):
                try:
                    os.unlink(lp.extended(path))
                except OSError:
                    pass
            return False

    def _extract_zip_into(self, archive_path: Path, dest: Path) -> None:
        """把 zip 解进 ``dest``，逐条做 zip-slip 校验（任何逃逸条目直接拒绝）。"""
        import zipfile

        from . import fsutil

        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.namelist():
                if fsutil.safe_join(dest, member) is None:
                    raise ValueError(f"压缩包里有非法路径: {member}")
            archive.extractall(dest)

    def import_mod_begin(self, file_name: str) -> dict[str, Any]:
        """开始**分块**接收拖进来的压缩包。

        为什么要分块：pywebview 的 js_api 参数走 WebView2 的消息通道，一次性把几十 MB
        的 base64 丢过去会**先卡住再闪退**（2026-10-01 用户实测：「拖 zip 进去会卡在解压
        和识别角色，然后闪退」）。改成前端每块 1 MB、逐块调用，后端追加写临时文件。
        """
        name = Path(str(file_name or "")).name
        suffix = Path(name).suffix.lower()
        if suffix not in IMPORT_SUFFIXES:
            # ⚠️ **"不支持"也要说清目标库在哪**（2026-10-03 用户：「下载或拖入**解压失败
            # 或不支持**没有弹出**目标库和文件原位置**，让用户手动解压」）。
            # 这条比"解压失败"更早触发（文件还没传完就拒了），所以拿不到"文件在哪"——
            # 但**目标库**是明确的，而且用户拖的那个包就在他自己手上。
            return {"ok": False,
                    "target_dir": str(self.config.library_path),
                    "message": (
                        f"这个格式不能自动导入（只支持 {IMPORT_SUFFIX_HINT}）：{name or '（没拿到文件名）'}\n\n"
                        f"**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：\n"
                        f"  {self.config.library_path}\n\n"
                        "手动做法：把你拖进来的那个包解压，得到里面的 Mod 文件夹"
                        "（如果解压出来套了好几层，保留最外层那一层），"
                        "整个放进上面的目录，再回界面点「重新扫描」。")}
        import time as _time

        incoming = self.config.runtime_path / "_incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        token = f"{int(_time.time())}-{os.getpid()}-{abs(hash(name)) % 100000}"
        # 后缀必须带上：解压时按它选解压器（.zip → 标准库；.7z/.rar → 7-Zip / bsdtar）
        part = incoming / f"{token}{suffix}.part"
        try:
            part.write_bytes(b"")
        except OSError as exc:
            return {"ok": False, "message": f"创建临时文件失败：{exc}"}
        sessions = getattr(self, "_import_sessions", None)
        if sessions is None:
            sessions = {}
            self._import_sessions = sessions
        sessions[token] = {"path": part, "name": name, "size": 0}
        launcher._append_log(self.config, f"导入: 开始接收 {name}（分块）")
        return {"ok": True, "token": token, "suffix": suffix}

    def import_mod_chunk(self, token: str, data_b64: str) -> dict[str, Any]:
        """接收一个分块（base64）。"""
        sessions = getattr(self, "_import_sessions", None) or {}
        info = sessions.get(str(token))
        if not info:
            return {"ok": False, "message": "导入会话已失效，请重新拖入"}
        import base64

        try:
            blob = base64.b64decode(data_b64 or "", validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"分块解码失败：{exc}"}
        try:
            with open(info["path"], "ab") as handle:
                handle.write(blob)
        except OSError as exc:
            return {"ok": False, "message": f"写入分块失败：{exc}"}
        info["size"] += len(blob)
        # ⚠️⚠️ **这里原来卡了 600 MB 限额，2026-10-03 按用户要求（选 A）去掉**。
        #
        # 用户反馈：「**mod 超过 600mb 就显示请手动解压放入，但是动态还一直卡在那里，
        # 为什么定额这么低**」—— 两件事：
        #   ① **限额本身过时**：这个 600 MB 来自更早"一次性 base64 传整包"的时代
        #      （那条路在 `import_mod_archive`，限额 300 MB，注释写着"避免超大包把内存
        #      和调用参数撑爆"）。而**分块这条路是流式直接 `open(...,"ab")` 写磁盘的，
        #      全程不把整包读进内存** ⇒ 没有技术上必须卡在 600 MB 的理由。
        #   ② **超限时的写法就是"卡住"的根因**：原实现只 `return {"ok": False}` ——
        #      **不删**已写进磁盘的 `.part`、**不清理** `_import_sessions` 会话、
        #      **不更新**任务状态 ⇒ 进度停在超限那一刻、临时文件留在 `runtime\_incoming\`，
        #      用户看到的就是"提示出来了，但动态一直卡在那里"。
        #
        # 现在：**不再按大小拒绝**（只靠磁盘空间），但保留一个"防呆"上限
        # `IMPORT_HARD_CAP_BYTES`，且**一旦触发就彻底清理并如实说明**。
        if info["size"] > IMPORT_HARD_CAP_BYTES:
            self._abort_import_session(str(token), info)
            return {
                "ok": False,
                "aborted": True,
                "message": (f"这个包太大了（已超过 {IMPORT_HARD_CAP_BYTES // (1024 ** 3)} GB），"
                            f"已中止导入并清理掉临时文件。\n"
                            f"如果确实要装这么大的包，请先解压，再把里面的 Mod 文件夹拖进 Mod 库。"),
            }
        return {"ok": True, "received": info["size"]}

    def _abort_import_session(self, token: str, info: dict[str, Any]) -> None:
        """中止一次导入：**把临时文件和会话都清干净**（2026-10-03）。

        为什么必须有它：原来超限/失败时只返回一句错误，`.part` 留在
        `runtime\\_incoming\\`、会话留在 `_import_sessions` —— 用户看到"提示出来了、
        但动态卡在那里"，磁盘上还留着半截大文件。
        """
        sessions = getattr(self, "_import_sessions", None)
        if isinstance(sessions, dict):
            sessions.pop(str(token), None)
        try:
            path = info.get("path")
            if path:
                Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def import_mod_finish(self, token: str) -> dict[str, Any]:
        """分块接收完毕：落盘完成 → 走与一次性导入完全相同的解压 + 收编流程。"""
        sessions = getattr(self, "_import_sessions", None) or {}
        info = sessions.pop(str(token), None)
        if not info:
            return {"ok": False, "message": "导入会话已失效，请重新拖入"}
        part: Path = info["path"]
        if not part.is_file() or part.stat().st_size == 0:
            return {"ok": False, "message": "没有收到文件内容"}
        # 接收期用 `<token><后缀>.part` 命名（半截文件一眼能认出来），但解压器是按
        # **扩展名**挑的 —— 带着 `.part` 会让 7z/rar 被判成"不支持的格式"（2026-10-01
        # 实测：拖 .7z 报 `unsupported archive format: …60000.7z.part`）。
        # 所以这里先原子改名成 `<token><后缀>` 再解压，最后两个名字都清掉。
        staged = part
        if part.name.lower().endswith(".part"):
            staged = part.with_name(part.name[:-len(".part")])
            try:
                part.replace(staged)
            except OSError:
                staged = part
        try:
            return self._import_archive_file(staged, str(info["name"]))
        finally:
            for candidate in {staged, part}:
                try:
                    candidate.unlink()
                except OSError:
                    pass

    def import_mod_archive(self, file_name: str, data_b64: str) -> dict[str, Any]:
        """把拖进界面的压缩包（`.zip` / `.7z` / `.rar`）解压进 Mod 库（**一次性传**，小包用）。

        用户需求（原话）：「如果在 Mod 库界面，能直接拖 zip 进去，然后自动解压，解析角色归属」，
        2026-10-01 追加：「需要增加支持拖入 7z」「rar 也要」。

        为什么走 base64：pywebview 拿不到拖放文件的**本地路径**（WebView2 沙箱里
        `File.path` 不可用），所以前端用 `FileReader` 读出内容再传过来。为避免超大包
        把内存和调用参数撑爆，超过 `max_bytes` 直接拒绝并提示改用文件选择。
        """
        import base64

        name = Path(str(file_name or "")).name
        suffix = Path(name).suffix.lower()
        if suffix not in IMPORT_SUFFIXES:
            # ⚠️ **"不支持"也要说清目标库在哪**（2026-10-03 用户：「下载或拖入**解压失败
            # 或不支持**没有弹出**目标库和文件原位置**，让用户手动解压」）。
            # 这条比"解压失败"更早触发（文件还没传完就拒了），所以拿不到"文件在哪"——
            # 但**目标库**是明确的，而且用户拖的那个包就在他自己手上。
            return {"ok": False,
                    "target_dir": str(self.config.library_path),
                    "message": (
                        f"这个格式不能自动导入（只支持 {IMPORT_SUFFIX_HINT}）：{name or '（没拿到文件名）'}\n\n"
                        f"**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：\n"
                        f"  {self.config.library_path}\n\n"
                        "手动做法：把你拖进来的那个包解压，得到里面的 Mod 文件夹"
                        "（如果解压出来套了好几层，保留最外层那一层），"
                        "整个放进上面的目录，再回界面点「重新扫描」。")}
        # ⚠️ **两条路的限额必须一致**（2026-10-03）：原来是 300 MB，而分块那条是 600 MB，
        # 同一个包"拖进去"和"走另一条路"结果不同，用户会莫名其妙。
        # 现在共用同一个**防呆**上限（见 `IMPORT_HARD_CAP_BYTES` 的说明）。
        # ⚠️ 注意这条是**一次性 base64 传整包**的老路径，它**真的会把整包读进内存**，
        # 所以超大包建议走分块那条（前端默认就是分块）。
        max_bytes = IMPORT_HARD_CAP_BYTES
        try:
            blob = base64.b64decode(data_b64 or "", validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"数据解码失败：{exc}"}
        if not blob:
            return {"ok": False, "message": "没有收到文件内容"}
        if len(blob) > max_bytes:
            return {"ok": False,
                    "message": f"压缩包太大（{len(blob) / 1048576:.1f} MB），"
                               f"超过 {max_bytes // (1024 ** 3)} GB —— 这么大的包请先解压，"
                               f"再把里面的 Mod 文件夹拖进 Mod 库"}

        incoming = self.config.runtime_path / "_incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        archive_path = incoming / name
        try:
            archive_path.write_bytes(blob)
        except OSError as exc:
            return {"ok": False, "message": f"写入临时文件失败：{exc}"}
        try:
            return self._import_archive_file(archive_path, name)
        finally:
            try:
                archive_path.unlink()
            except OSError:
                pass

    def import_manual_mods(self) -> dict[str, Any]:
        """把手动放进 Mods 目录的 Mod 收编进库，并在界面里标记为已开启。

        用户需求（原话）：「手动放进去的和库里的进行比对，如果库里已有，就在 UI 中
        显示那个开启，库里没有就把它放到库里，然后显示开启」。

        实现见 ``activation.import_manual_mods``：比对时先按目录名、再按 ini 里的
        namespace 特征（容忍改过名）；收编成功后会把手动目录从 Mods 移除，避免与随后
        stage 出的 ``MC_<角色>_<名字>`` 构成同角色成对（那会让游戏直接崩）。
        """
        from . import activation

        synced = activation.import_manual_mods(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        if synced.get("found"):
            # 库内容变了，必须让扫描缓存失效，否则界面仍显示旧状态
            self._invalidate_mods()
        return synced

    # ------------------------------------------------------------------
    # 角色归属确认（匹配不确定时弹窗让用户选择）
    # ------------------------------------------------------------------
    def known_characters(self) -> list[str]:
        """可选角色名单，供弹窗下拉使用。"""
        names = [name for name, _aliases in core.load_character_aliases()]
        for mod in self._mods():
            group = (mod.group or "").strip()
            if group and group not in names and group != "未分类" and not mod.is_dependency:
                names.append(group)
        return names

    def pending_characters(self) -> dict[str, Any]:
        """列出**角色归属不确定**的 Mod，供界面弹窗让用户选择。

        用户需求（原话）：「如果不确定就弹窗让用户选择」。

        `confidence` 的语义见 `core.match_character_detail`：
        ``low`` = 匹配到了但无法确定谁才是主体（例如名字写在括号说明里、或出现多个
        角色名分不清主次）；``none`` = 一个都没匹配到。两者都交给用户定夺 ——
        猜错的代价是同角色互斥失效，两个同角色 Mod 会同时生效并崩游戏。
        """
        pending: list[dict[str, Any]] = []
        for mod in self._mods():
            if mod.is_dependency:
                continue
            if mod.char_confidence in ("low", "none"):
                pending.append({
                    "id": mod.id,
                    "name": mod.name,
                    "path": str(mod.path),
                    "group": mod.group,
                    "confidence": mod.char_confidence,
                    "candidates": list(mod.char_candidates),
                    # **预识别**（用户 2026-10-01 要求「对没法完全确定归属的 Mod 进行预识别，
                    # 匹配与哪个角色相关字数最多」）：前端拿它做下拉的默认选中项 ——
                    # 但黄字"角色待确认"照旧显示，必须用户点一下才算数。
                    "guess": mod.char_guess,
                })
        return {"pending": pending, "total": len(pending), "known": self.known_characters()}

    def set_mod_kind(self, mod_id: str, kind: str) -> dict[str, Any]:
        """把 Mod 在「皮肤 Mod」与「辅助 Mod」之间移动（用户手动纠正误识别）。

        用户 2026-10-03：「**一些被误识别的 mod 可以在辅助和皮肤之间移动**」。
        自动判据（`core.infer_kind_and_group`）永远只能猜，猜错了必须让用户一句话改过来 ——
        与"角色归属"同一套做法：写进该 Mod 目录下的 `mod.meta.json`，此后扫描即为显式值。

        `kind` 只接受 `assist`（辅助 Mod）与 `character`（皮肤 Mod）两个值。
        """
        want = str(kind or "").strip().lower()
        if want not in ("assist", "character"):
            return {"ok": False, "message": "只能移到「辅助 Mod」或「皮肤 Mod」"}
        target = next((m for m in self._mods() if m.id == mod_id), None)
        if target is None:
            return {"ok": False, "message": f"找不到 Mod: {mod_id}"}

        meta_path = target.path / "mod.meta.json"
        payload: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload["kind"] = want
        payload.setdefault("id", target.id)
        payload.setdefault("name", target.name)
        # 移成辅助 Mod 时清掉角色归属（辅助 Mod 不参与同角色互斥）；
        # 移回皮肤 Mod 时不动 group，让用户自己再选一次归属。
        if want == "assist":
            payload.pop("character", None)
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "message": f"写入失败: {exc}"}
        return {"ok": True, "kind": want, "name": target.name}

    def set_mod_group(self, mod_id: str, group: str) -> dict[str, Any]:
        """把辅助 Mod 归到某个**分组**（加载页与壁纸 / 界面功能类 / 工具画质类 / 其它辅助）。

        为什么单开一个接口（2026-10-03 用户实测）：
        「我选了加载页与壁纸，他直接被归类到了角色 mod，而且新建了一个角色叫这个」——
        原先只有一个「归属」下拉，辅助的分组名被塞进了角色接口，
        `set_mod_character` 里那句 `payload["group"] = character` 就把它同时写成了角色。
        用户随后给了正确的设计：「那个下拉可以拆成两个，上面一个选择是服装还是辅助，
        下面那个选择细分」⇒ 类型走 `set_mod_kind`，细分里的"分组"走本方法。

        语义：只改 `group` / `kind`，**不动 `character`**（辅助 Mod 本来就不属于任何角色）。
        """
        from . import launcher
        from .core import ASSIST_GROUP_HIDE, ASSIST_GROUP_OTHER, ASSIST_GROUP_TOOL, WALLPAPER_GROUP

        allowed = [WALLPAPER_GROUP, ASSIST_GROUP_HIDE, ASSIST_GROUP_TOOL, ASSIST_GROUP_OTHER]
        group = (group or "").strip() or ASSIST_GROUP_OTHER
        if group not in allowed:
            return {"ok": False, "message": f"「{group}」不是有效的辅助分组（可选：{' / '.join(allowed)}）"}
        target = next((m for m in self._mods() if m.id == mod_id), None)
        if target is None:
            return {"ok": False, "message": f"找不到 Mod: {mod_id}"}
        meta_path = target.path / "mod.meta.json"
        payload: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload["kind"] = "assist"
        payload["group"] = group
        # 辅助 Mod 不属于任何角色 —— 顺手把误写进去的角色清掉（那是老 bug 的残留）
        payload["character"] = ""
        payload.setdefault("id", target.id)
        payload.setdefault("name", target.name)
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "message": f"写入失败: {exc}"}
        self._invalidate_mods()
        launcher._append_log(self.config, f"辅助分组已设定: {target.name} -> {group}")
        return {"ok": True, "group": group}

    def set_mod_character(self, mod_id: str, character: str) -> dict[str, Any]:
        """把用户选定的角色写进该 Mod 的 `mod.meta.json`，此后扫描即为高置信。"""
        character = (character or "").strip()
        # ⚠️⚠️ **分组名不许当角色写**（2026-10-03 用户实测）：
        #   「我选了加载页与壁纸，他直接被归类到了角色 mod，而且新建了一个角色叫这个」
        # 根因是本方法下面那句 `payload["group"] = character` —— 它把传进来的字符串
        # **同时**当成角色和分组写下去；而辅助页那个分类下拉传的是**分组名**
        #（`加载页与壁纸` / `界面功能类` / `工具画质类` / `其它辅助`），
        # 于是角色表里凭空多出一个叫"加载页与壁纸"的角色。
        # 这里直接挡掉：分组名走 `set_mod_group`，这个接口只收**角色名**（或空 = 未分类）。
        try:
            from .core import ASSIST_GROUP_HIDE, ASSIST_GROUP_OTHER, ASSIST_GROUP_TOOL, WALLPAPER_GROUP

            reserved = {WALLPAPER_GROUP, ASSIST_GROUP_HIDE, ASSIST_GROUP_TOOL, ASSIST_GROUP_OTHER}
        except Exception:  # noqa: BLE001
            reserved = {"加载页与壁纸", "界面功能类", "工具画质类", "其它辅助"}
        if character in reserved:
            return {
                "ok": False,
                "message": (
                    f"「{character}」是**分组名**，不是角色名 —— 请用「分类」来改它，"
                    "不要用「更改归属」"
                ),
            }
        # ⚠️ **允许留空 = 未分类**。原来这里写死"角色名不能为空"，而前端文案一直写着
        # "留空 = 保持未分类"，两边直接打架（用户 2026-10-03：「说了留空 = 保持未分类，
        # 设定又说不能留空」）。语义上"未分类"是合法状态：壁纸/加载页这类 Mod 本就不属于
        # 任何角色，不应该被迫选一个。
        target = next((m for m in self._mods() if m.id == mod_id), None)
        if target is None:
            return {"ok": False, "message": f"找不到 Mod: {mod_id}"}

        meta_path = target.path / "mod.meta.json"
        payload: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload["group"] = character
        payload["character"] = character
        payload.setdefault("id", target.id)
        payload.setdefault("name", target.name)
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "message": f"写入失败: {exc}"}

        self._invalidate_mods()
        launcher._append_log(self.config, f"角色归属已确认: {target.name} -> {character}")
        return {"ok": True, "id": mod_id, "character": character, "meta_path": str(meta_path)}

    def set_mod_kind(self, mod_id: str, kind: str) -> dict[str, Any]:
        """把某个 Mod 标成「辅助 mod」或「角色 mod」（写进它的 `mod.meta.json`）。

        用户 2026-10-01 要求（方案④）：自动识别 + **手动纠正** + 独立页签。
        自动识别只认"没有换装资源 + 跳过绘制型/辅助关键词 + **归不到任何角色**"的包；
        像「去面具 / 去圆环」这种其实属于角色变体的，或反过来想当辅助管的，都在这里手动改 ——
        写了 ``kind`` 之后，扫描时**显式 meta 优先于自动识别**（见 `core.infer_kind_and_group`）。
        """
        kind = (kind or "").strip().lower()
        if kind not in {"assist", "character"}:
            return {"ok": False, "message": "kind 只能是 assist 或 character"}
        target = next((m for m in self._mods() if m.id == mod_id), None)
        if target is None:
            return {"ok": False, "message": f"找不到 Mod: {mod_id}"}

        meta_path = target.path / "mod.meta.json"
        payload: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}
        payload["kind"] = kind
        payload.setdefault("id", target.id)
        payload.setdefault("name", target.name)
        try:
            meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            return {"ok": False, "message": f"写入失败: {exc}"}

        self._invalidate_mods()
        label = "辅助 Mod" if kind == "assist" else "角色 Mod"
        launcher._append_log(self.config, f"已标记为{label}: {target.name}")
        return {"ok": True, "id": mod_id, "kind": kind, "meta_path": str(meta_path)}

    def ensure_initialized(self) -> dict[str, Any]:
        """手动跑一次文件层初始化自检（不含注入库；一键启动请用 prepare_launch）。"""
        from . import initialize

        launcher._append_log(self.config, "初始化自检 requested from UI")
        report = initialize.ensure_all(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        return report

    # ------------------------------------------------------------------
    # 组件版本 / 更新
    # ------------------------------------------------------------------
    def component_versions(self) -> dict[str, Any]:
        from . import updates

        return updates.component_versions(self.config)

    # ------------------------------------------------------------------
    # 程序自身版本 / 自我更新（右上角的更新检测）
    # ------------------------------------------------------------------
    def get_app_info(self) -> dict[str, Any]:
        from .version import REPO_URL

        return {
            "version": selfupdate.current_version(),
            "repo": REPO_URL,
            "frozen": selfupdate.is_frozen(),
            "exe": str(selfupdate.executable_path() or ""),
        }

    # ------------------------------------------------------------------
    # 下载加速 / 线路（按需临时启用，用完即放；见 fastnet）
    # ------------------------------------------------------------------
    def open_external(self, url: str) -> dict[str, Any]:
        """用系统默认浏览器打开链接（只允许 http/https，避免被塞本地路径）。"""
        import webbrowser

        if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
            return {"ok": False, "message": "只支持 http/https 链接"}
        try:
            webbrowser.open(url)
            launcher._append_log(self.config, f"打开链接: {url}")
            return {"ok": True, "url": url}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}

    def get_download_settings(self) -> dict[str, Any]:
        from . import fastnet

        return {
            "policy": fastnet.get_policy(),
            "line_mode": fastnet.get_line_mode(),
            "lines": fastnet.line_status(),
            "status": fastnet.status(),
        }

    def set_download_settings(self, policy: str = "", line_mode: str = "") -> dict[str, Any]:
        from . import fastnet

        if policy:
            fastnet.set_policy(policy)
            self.config.download_boost = fastnet.get_policy()
        if line_mode:
            fastnet.set_line_mode(line_mode)
            self.config.download_line = fastnet.get_line_mode()
        try:
            self.config.save()
        except OSError:
            pass
        launcher._append_log(
            self.config,
            f"下载设置: 加速={fastnet.get_policy()} 线路={fastnet.get_line_mode()}",
        )
        return self.get_download_settings()

    def clear_download_lines(self) -> dict[str, Any]:
        from . import fastnet

        fastnet.clear_line_cache()
        launcher._append_log(self.config, "已清除下载线路记录")
        return self.get_download_settings()

    def check_app_update(self, use_cache: bool = False) -> dict[str, Any]:
        """对比 GitHub release 的 tag 与本机版本号。

        ⚠️ **默认改成"强制查"（`use_cache=False`）**（2026-10-04 用户实测踩到的坑）：

        `selfupdate.CHECK_CACHE_SECONDS` 是 **6 小时**，而且这份缓存是**落盘**的
        （`runtime\\_update\\last_check.json`）。只要落盘那一刻新版本**还没发布**，
        之后整整 6 小时内、所有走缓存的检查都会一口咬定"已是最新" ——
        用户那次的现象正是如此：缓存写于 11:32（`latest=v1.0.7`），而 **v1.0.8 是 11:51
        才发布的**，于是伪旧版一路"更新"到的还是 1.0.7。而设置页那个「检查程序更新」
        按钮走的**恰好是不传参的默认值** ⇒ 用户点了也白点，看到的仍是缓存里的旧结论。

        所以分工现在是明确的、并且由签名固定住：
          * **启动时的自动检查**（`UpdateBadge.autoCheck`）**显式传 `True`** ——
            省 API 额度、离线时静默，这条本来就不该每次打网络；
          * **任何"用户主动点"的入口**（角标、设置页按钮）走这个默认值 `False` ——
            点了就真的打一次网络。
        """
        return selfupdate.check_update(
            self.config,
            log=lambda message: launcher._append_log(self.config, message),
            use_cache=use_cache,
        )

    def download_app_update(self) -> dict[str, Any]:
        return selfupdate.download_update(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )

    def apply_app_update(self) -> dict[str, Any]:
        """替换 exe 并自动重启（源码运行模式只提示 git pull）。"""
        result = selfupdate.apply_update(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        if result.get("ok") and result.get("restart"):
            # 留一点时间让前端把提示画出来，然后退出，交给 VBS 换文件并重启
            threading.Timer(1.8, lambda: os._exit(0)).start()
        return result

    def start_app_update(self) -> dict[str, Any]:
        """在依赖页里跑自更新：复用依赖任务的进度条与轮询接口（用户要求）。

        前端调它之后切到依赖页并轮询 get_dependency_progress，就能看到进度条与日志。
        """
        if self._dep_task and self._dep_task.get("running"):
            return self.get_dependency_progress()
        self._dep_task = {
            "running": True,
            "current": 0,
            "total": 1,
            "percent": 0.0,
            "message": "正在检查程序更新…",
            "log": [],
            "results": [],
            "app_update": True,
        }
        task = self._dep_task

        def log(message: str) -> None:
            task["log"].append(message)
            launcher._append_log(self.config, message)

        def finish(status: str, message: str) -> None:
            task["results"] = [{"key": "endfieldmodcontroller", "status": status, "message": message}]
            task["message"] = message
            task["percent"] = 100.0
            # 失败/异常也要落到 launch.log：以前只写内存里的任务状态，程序一退就没了，
            # 事后根本查不出"那一项失败"到底是什么（2026-10-01 实测踩到）。
            if status not in ("已更新", "已是最新"):
                launcher._append_log(self.config, f"自更新{status}：{message}")

        def worker() -> None:
            try:
                info = selfupdate.check_update(self.config, use_cache=False)
                if info.get("error"):
                    finish("失败", f"检查更新失败：{info['error']}")
                    return
                current, latest = info.get("current"), info.get("latest")
                if not info.get("update_available"):
                    finish("已是最新", f"v{current} 已是最新")
                    return
                task["message"] = f"正在下载 v{latest}…"

                def on_progress(done: int, total: int) -> None:
                    # ⚠️⚠️ **自更新也要写日志与实时速度**（2026-10-03 用户报
                    # 「**安装日志一直不动，也没下载速度，条在走**」）。
                    # 原来这里**只写 percent**，所以进度条会走，而日志框纹丝不动、
                    # 速度卡片永远是「—」—— 用户根本看不出下载有没有在动。
                    if not total:
                        return
                    import time as _t

                    now = _t.time()
                    task["percent"] = min(99.0, done * 100.0 / total)
                    task["message"] = (f"下载 v{latest}：{done // 1048576}/"
                                       f"{max(total // 1048576, 1)} MB")
                    task["bytes_received"] = int(done)
                    task["expected_bytes"] = int(total)
                    task["byte_percent"] = round(min(99.0, done * 100.0 / total), 1)
                    task["running"] = True

                    # ① 实时速度：与依赖下载同一套算法（前后采样差 + 指数平滑）
                    prev_bytes = task.get("_speed_bytes")
                    prev_at = task.get("_speed_at")
                    if prev_bytes is not None and prev_at is not None and now > prev_at:
                        instant = (int(done) - int(prev_bytes)) / (now - float(prev_at))
                        if instant >= 0:
                            old_speed = float(task.get("speed_bps") or 0.0)
                            task["speed_bps"] = (instant if old_speed <= 0
                                                 else old_speed * 0.6 + instant * 0.4)
                    task["_speed_bytes"] = int(done)
                    task["_speed_at"] = now

                    # ② 日志：每跨过 10% 或距上次超过 3 秒记一条（别刷屏）
                    pct = int(done * 100 / total)
                    last_pct = int(task.get("_upd_last_pct", -10))
                    last_at = float(task.get("_upd_last_at", 0.0))
                    if pct >= last_pct + 10 or (now - last_at) > 3.0:
                        speed = float(task.get("speed_bps") or 0.0)
                        speed_text = (f"  {speed / 1048576:.2f} MB/s" if speed > 0 else "")
                        task.setdefault("log", []).append(
                            f"下载更新包 v{latest}：{pct}%"
                            f"（{done / 1048576:.1f}/{total / 1048576:.1f} MB）{speed_text}")
                        task["_upd_last_pct"] = pct
                        task["_upd_last_at"] = now

                result = selfupdate.download_update(
                    self.config, url=info.get("download_url", ""),
                    digest=info.get("digest", ""), log=log, progress=on_progress,
                )
                if not result.get("ok"):
                    finish("失败", f"下载失败：{result.get('message')}")
                    return
                # **下载完成先停下，交给用户决定何时安装**（用户 2026-10-01 要求：
                # 「下载完应该跳一个弹窗，让用户选择是立即重启程序更新还是稍后」）。
                # 前端看到 status="已下载" 会弹确认框：
                #   立即 → 调 apply_app_update()（替换 + 自动重启）
                #   稍后 → 保留 runtime\_update\ 里的更新包，下次启动时再由 pending_update 提示
                task["message"] = f"v{latest} 已下载完成，等待你选择何时安装"
                task["pending_apply"] = True
                finish("已下载", f"v{latest} 已下载完成，可以立即重启安装，或稍后再说")
            except Exception as exc:  # noqa: BLE001
                finish("失败", f"{exc}")
            finally:
                task["running"] = False

        threading.Thread(target=worker, name="mc-app-update", daemon=True).start()
        return self.get_dependency_progress()

    def check_component_updates(self) -> dict[str, Any]:
        from . import updates

        launcher._append_log(self.config, "检查组件更新 requested from UI")
        report = updates.check_updates(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )
        # DLSS5 组件（ReShade 底座 / DLSS5-Feeder / iMMERSE）也一并检查
        try:
            report["dlss5"] = dlss5_fetcher.check_updates(
                self.config, log=lambda message: launcher._append_log(self.config, message)
            )
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(f"DLSS5 组件检查失败: {exc}")
        return report

    def _sync_firstperson_ini_after_install(self) -> dict[str, Any]:
        """组件装完后**立刻**把第一人称的设置写进"生效那份" ReShade.ini。

        用户 2026-10-04 原话：「这个要加进一键下载流程里，**每次下载第一人称 mod 时都要改**」。

        为什么不能只靠一键启动：依赖页点「一键安装/更新全部组件」之后，用户完全可能
        **直接进游戏**（不走一键启动）—— 而那时生效那份（`runtime\\reshade\\ReShade.ini`，
        由 `RESHADE_BASE_PATH_OVERRIDE` 决定）里还可能是插件写的出厂值
        （`Language=0` 英文、`Font=` 空 ⇒ 中文画方块），第一人称就成了英文。
        下载/安装完组件就写一次，等于"装好即中文"。

        幂等：只补差异（缺段补段、缺键补键），改前留 `.bak-before-enhancer-sync`，
        已设过的非空字体不会被覆盖。
        """
        try:
            result = launcher.sync_effective_reshade_ini(
                self.config, log=lambda message: launcher._append_log(self.config, message))
        except Exception as exc:  # noqa: BLE001 —— 写 ini 失败不该让"安装成功"变成失败
            launcher._append_log(self.config, f"WARN 第一人称设置同步失败（忽略）: {exc}")
            return {}
        if result.get("enhancer") or result.get("style") or result.get("created"):
            launcher._append_log(
                self.config,
                f"第一人称设置已随组件安装写入生效那份 ReShade.ini"
                f"（第一人称 {result.get('enhancer', 0)} 项、字体 {result.get('style', 0)} 项）",
            )
        return result

    def install_dlss5_component(self, key: str, force: bool = False) -> dict[str, Any]:
        """单项安装/更新一个 DLSS5 组件（依赖页与更新页共用）。"""
        launcher._append_log(self.config, f"安装 DLSS5 组件 {key} requested from UI")
        try:
            result = dlss5_fetcher.install(
                self.config, key,
                log=lambda message: launcher._append_log(self.config, message),
                force=force,
            )
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"安装 {key} 失败: {exc}")
            return {"ok": False, "changed": False, "key": key, "message": str(exc)}
        launcher._append_log(self.config, f"安装 {key}: {result.get('message', '')}")
        # 「每次下载第一人称 mod 时都要改」（用户 2026-10-04）：装完立刻把
        # `[endfield-enhancer]`（中文 + 与 EFMI 共存必需项）写进**生效那份** ini，
        # 这样不点一键启动、直接进游戏也是中文。幂等，且失败不影响安装结果。
        self._sync_firstperson_ini_after_install()
        return result

    def install_all_new_components(self) -> list[dict[str, Any]]:
        """把"不随包分发"的在线组件一次装齐（缺什么装什么）。"""
        launcher._append_log(self.config, "一键安装全部在线组件 requested from UI")
        results = dlss5_fetcher.ensure_all(
            self.config,
            log=lambda message: launcher._append_log(self.config, message),
            only_missing=False,
        )
        if self.config.use_builtin_runtime:
            try:
                for item in runtime_deps.ensure_all(self.config):
                    results.append({"key": item.key, "status": item.status, "message": item.message})
            except Exception as exc:  # noqa: BLE001
                results.append({"key": "builtin", "status": "失败", "message": str(exc)})
        self._sync_firstperson_ini_after_install()
        return results

    def update_component(self, name: str, url: str = "") -> dict[str, Any]:
        from . import updates

        launcher._append_log(self.config, f"更新组件 {name} requested from UI")
        try:
            if name == "reshade":
                # 走 dlss5_fetcher（纯标准库解包，不再依赖系统 7z.exe；
                # 旧的 updates.update_reshade_base 在没有 7z 的机器上直接失败）
                result = dlss5_fetcher.install(
                    self.config, "reshade_base",
                    log=lambda message: launcher._append_log(self.config, message),
                )
                return {
                    "ok": bool(result.get("ok")),
                    "version": result.get("version", ""),
                    "message": result.get("message", ""),
                    "note": result.get("note", ""),
                    "changed": bool(result.get("changed")),
                }
            if name == "secondary_motion":
                return updates.update_secondary_motion(
                    self.config, url=url, log=lambda message: launcher._append_log(self.config, message)
                )
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"更新 {name} 失败: {exc}")
            return {"ok": False, "message": str(exc)}
        return {"ok": False, "message": f"未知组件: {name}"}

    def enable_d3d12_proxy_mode(self) -> dict[str, Any]:
        launcher._append_log(self.config, "d3d12 proxy mode requested from UI")
        try:
            return launcher.enable_d3d12_proxy_mode(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"d3d12 proxy mode failed: {exc}")
            raise

    def restore_d3d12_proxy_mode(self) -> dict[str, Any]:
        launcher._append_log(self.config, "restore d3d12 proxy mode requested from UI")
        try:
            return launcher.restore_d3d12_proxy_mode(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"restore d3d12 proxy mode failed: {exc}")
            raise

    # ------------------------------------------------------------------
    # game directory injection audit
    # ------------------------------------------------------------------
    def game_multi_instance_status(self) -> dict[str, Any]:
        """防多开：当前是否有终末地在跑。"""
        try:
            return launcher.check_game_multi_instance(self.config)
        except Exception as exc:  # noqa: BLE001
            return {"running": False, "processes": [], "blocked": False, "message": str(exc)}

    # ------------------------------------------------------------------
    # 游戏目录体检 / 备份净化 / 还原（game_clean）
    # ------------------------------------------------------------------
    def game_clean_audit(self) -> dict[str, Any]:
        """列出游戏目录里所有**原版不会有**的东西（proxy、plugin payload、插件日志…）。"""
        from . import game_clean

        try:
            report = game_clean.audit(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"game clean audit failed: {exc}")
            return {"ok": False, "message": str(exc), "findings": [],
                    "injections": 0, "multi_instance": 0}
        # ⚠️ 两个字段是**给前端补齐的**（2026-10-04 修前后端不匹配）：设置页的
        # 「游戏目录体检」结果框读 `r.injections` 与 `r.multi_instance`，而 audit 只给
        # `findings`/`counts` ⇒ 界面上**恒显示"第三方注入文件：0 个"**、多实例警告永不出现。
        # 数据都是真实存在的（findings 条数 + 正在跑的终末地进程数），这里如实补上。
        if isinstance(report, dict):
            report.setdefault("injections", len(report.get("findings") or []))
            try:
                multi = launcher.check_game_multi_instance(self.config)
                report["multi_instance"] = len(multi.get("processes") or [])
            except Exception:  # noqa: BLE001 —— 进程枚举失败不该让体检整体失败
                report["multi_instance"] = 0
        return report

    def game_clean_backup_and_clean(self, include_plugin_data: bool = True) -> dict[str, Any]:
        """先整体备份，再把游戏目录净化成原版（只移动不删除，可一键还原）。"""
        from . import game_clean

        launcher._append_log(self.config, "backup & clean game dir requested from UI")
        result = game_clean.backup_and_clean(
            self.config,
            log=lambda message: launcher._append_log(self.config, message),
            include_plugin_data=bool(include_plugin_data),
        )
        launcher._append_log(self.config, result.get("message", ""))
        return result

    def reset_dependencies_and_redownload(self) -> dict[str, Any]:
        """**依赖清空重新下载**（设置页最上面那个红按钮，用户 2026-10-02 要求）。

        用户原话：「设置页做一个依赖清空重新下载，**红色**，放在最上面，按了之后**清空除了
        mod 库和 exe 的所有文件和文件夹**，然后**还原终末地本体**，然后**跳转到依赖页开始
        一键下载依赖**」。

        三步（前端负责第三步的跳转与触发，这里做前两步）：
          ① 还原终末地本体（最近一次净化备份）；
          ② 清掉程序**自己的**运行数据：`runtime\\`（组件、缓存、日志、游戏备份、状态）
             与 `config.json`；然后用内存里的配置**原样写回**（路径设置全保留）。
          ③ 前端跳依赖页并开始「一键下载依赖」。

        ⚠️ 两条安全约束（为什么这里不写成"除了库和 exe 全删"）：
          * **只删认得的**：数据根里可能有用户自己放的东西（截图、笔记、别的工具），
            "除 X 全删"会连它们一起干掉；所以白名单只有 `runtime\\`、`assets\\` 与 `config.json*`。
          * **路径不许丢**：删 `config.json` 前先把库/备份仓/游戏目录这些记下来、马上写回 ——
            否则把库放在自定义盘的用户重启后会发现"库没了"（数据根换了、路径回到默认）。
        （用户 2026-10-02 追加：「assets\\ 也要删」—— 那 130 MB 随包资产会在下一步重新下载展开。）
        """
        import shutil

        base = Path(self.config.base_dir)
        runtime = Path(self.config.runtime_path)

        # ① 还原游戏本体（没有过净化备份时它自己会如实报"无需还原"）
        try:
            restore_info: dict[str, Any] = self.game_clean_restore("")
        except Exception as exc:  # noqa: BLE001
            restore_info = {"ok": False, "message": f"还原时出错：{exc}"}

        # ⚠️⚠️ **还原失败就不许往下清**（2026-10-04 审计发现的 P0）。
        #
        # 原来的顺序是「还原 → 无条件 rmtree(runtime)」，而 `restore_info` 的 ok/errors
        # **返回后从未被检查**。而 `runtime\game_backup\` 里放的是**唯一一份"净化前"的
        # 游戏目录文件** —— 还原本身就失败（清单损坏 / 备份源缺失 / 文件被占用）时再把它
        # 删掉，用户就永久停在"净化后"的状态：游戏目录缺 `d3dcompiler_47.dll` / `vulkan-1.dll`，
        # 第三方注入器已被移走，**而且再也没有任何办法还原**。
        # 同时被删掉的还有 `_state\crash_memory.json` / `proven_combos.json` / `file_watch.json`。
        # 这里的取舍很明确：**宁可让用户手动再点一次，也不能把唯一的还原点清掉。**
        if not restore_info.get("ok", True) or restore_info.get("errors"):
            # ⚠️⚠️ **"没有备份可还原" ≠ "还原失败"**（2026-10-05 修 —— 用户实测
            # 「依赖清空并重新下载按了报错」，日志原话：
            # `依赖清空: 已中止 —— 游戏本体还原未成功（没有找到任何游戏目录备份）`）。
            #
            # 为什么必然发生：这个按钮**第一次**跑的顺序是「① 还原游戏本体 → ② `rmtree(runtime)`」，
            # 而唯一的还原点 `runtime\game_backup\` **就在 runtime 里，被第 ② 步一起删掉**。
            # 于是第二次点就变成"没有找到任何游戏目录备份"，撞上下面这条保护 ⇒ 报错中止，
            # 用户从此再也点不动这个按钮；可这时游戏目录**本来就是上次还原过的样子**
            # （没有任何"该还原却还原不了"的东西）。
            #
            # 这条保护的目的是「**别把唯一还原点删掉**」（见下面的注释）。而
            # **没有备份 ⇒ 没有还原点可删** ⇒ 直接放行；只有"确实还有备份、却还原不了"
            # （清单损坏 / 文件被占用 / 备份源缺失）才继续中止。
            backups_left: list[Any] = []
            try:
                from . import game_clean

                backups_left = game_clean.list_backups(self.config)
            except Exception:  # noqa: BLE001 —— 判不出来时保守按"有备份"处理（保持原保护）
                backups_left = [{"unknown": True}]
            if backups_left:
                detail = restore_info.get("message") or "；".join(
                    str(x) for x in (restore_info.get("errors") or [])) or "未知原因"
                launcher._append_log(
                    self.config, f"依赖清空: 已中止 —— 游戏本体还原未成功（{detail}）")
                return {
                    "ok": False,
                    "aborted": "restore_failed",
                    "message": (
                        "已中止：**没能把游戏本体还原成原版**，所以这次没有清空任何东西。\n\n"
                        f"原因：{detail}\n\n"
                        "为什么必须中止：`runtime\\game_backup` 里是你唯一一份「净化前」的备份，"
                        "清空 runtime 会把它一起删掉 —— 那样游戏目录就再也回不去了。\n\n"
                        "可以先把游戏目录里被移走的文件手动放回（备份就在 runtime\\game_backup 下），"
                        "或者点「一键还原游戏本体」成功之后再回来清空。"
                    ),
                    "restore": restore_info,
                }
            launcher._append_log(
                self.config,
                "依赖清空: 没有游戏目录备份可还原（游戏目录已是上次还原过的状态）→ 继续清空")

        # ② 先记住关键路径（删完配置要原样写回）
        preserved: dict[str, Any] = {}
        for key in ("library_dir", "mod_backup_dir", "mod_backup_enabled", "game_exe",
                    "staging_mods_dir", "xxmi_launcher", "reshade_injection"):
            if hasattr(self.config, key):
                preserved[key] = getattr(self.config, key)

        removed: list[str] = []
        failed: list[str] = []
        if runtime.is_dir():
            try:
                shutil.rmtree(runtime)
                removed.append(str(runtime))
            except OSError:
                # 本进程还占着的文件（比如当前正在写的日志）删不掉 —— 逐个再试一遍，
                # 真删不掉的如实列出来，别假装清干净了
                for item in sorted(runtime.iterdir(), key=lambda path: (path.is_file(), path.name)):
                    try:
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                        removed.append(item.name)
                    except OSError:
                        failed.append(item.name)
        for cfg in list(base.glob("config.json*")):
            try:
                cfg.unlink()
                removed.append(cfg.name)
            except OSError:
                failed.append(cfg.name)
        # ④ 随包资产也清掉（用户 2026-10-02：「assets\\ 也要删」）——
        #    它会由下一步的「一键下载依赖」从 Release 拉 `assets-bundle.zip` 重新展开
        #    （约 130 MB，需要网络；国内通常要开加速器）。删不掉就如实说。
        assets = base / "assets"
        if assets.is_dir():
            try:
                shutil.rmtree(assets)
                removed.append(str(assets))
            except OSError as exc:
                failed.append(f"assets（{exc}）")

        # ③ 用内存里的配置重新落盘（路径保留；组件标记原本就在 runtime 里、已随它删掉）
        try:
            for key, value in preserved.items():
                setattr(self.config, key, value)
            self.config.ensure_dirs()
            self.config.save()
            self._mods_cache = None
        except Exception as exc:  # noqa: BLE001
            failed.append(f"写回配置失败：{exc}")

        launcher._append_log(
            self.config,
            f"依赖清空: 已删除 {len(removed)} 项，未删掉 {len(failed)} 项"
            + (f"（{', '.join(failed[:5])}）" if failed else "")
            + "；接着会重新下载依赖")
        return {
            "ok": True,
            "removed": removed,
            "failed": failed,
            "restore": restore_info,
            "kept": ["Mod 库", "Mod 备份仓", "程序 exe", "路径设置"],
        }

    def game_clean_restore(self, stamp: str = "") -> dict[str, Any]:
        """从备份还原游戏目录（回到净化前）。"""
        from . import game_clean

        launcher._append_log(self.config, "restore game dir from backup requested from UI")
        return game_clean.restore(
            self.config, stamp=stamp,
            log=lambda message: launcher._append_log(self.config, message),
        )

    def game_clean_backups(self) -> dict[str, Any]:
        from . import game_clean

        return {"backups": game_clean.list_backups(self.config)}

    def audit_game_injections(self) -> dict[str, Any]:
        """Report third-party loader DLLs / plugin payloads in the game folder.

        A proxy named ``d3dcompiler_47.dll``/``vulkan-1.dll``/... both replaces
        the genuine system module and injects ``plugin/*.dll`` into the game.
        Such leftovers invalidate every crash report, so the UI surfaces them.
        """
        try:
            return reshade_integration.audit_game_dir_injections(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"audit game injections failed: {exc}")
            return {"ok": False, "message": str(exc), "suspicious": [], "disabled": []}

    def clear_all_game_injections(self) -> dict[str, Any]:
        """**清除游戏目录里所有第三方注入**（先备份，可一键还原）—— 手动触发版。

        用户 2026-10-04 原话：「一键还原终末地清除所有第三方注入，**默认开**，
        开了之后**不管是不是管理器注入的，都要去掉（要备份）**」。

        与「启动前自动清除」开关**共用同一条实现**（`game_clean.backup_and_clean`），
        覆盖面最广：proxy DLL、`plugin\\*.dll`、3DMigoto 的 `d3dx.ini` / `ShaderFixes\\` /
        `loader_debug.log`、OptiScaler、ReShade 残留、DLSS5 专属运行库、被替换的 nvngx…
        **判定依据是"原版会不会有这个文件"**，所以不管是谁铺的都会被移走；
        移走前先整体备份到 `runtime\\game_backup\\<时间戳>\\`，随时可还原。
        """
        launcher._append_log(self.config, "clear all game injections requested from UI")
        from . import game_clean

        try:
            result = game_clean.backup_and_clean(
                self.config, log=lambda message: launcher._append_log(self.config, message))
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"clear all game injections failed: {exc}")
            raise
        moved = result.get("moved") or []
        if moved:
            result["message"] = (
                f"已清除 {len(moved)} 项第三方注入；备份在 {result.get('backup_dir')}"
                "（同页「撤销清除」可原样放回）"
            )
        return result

    def restore_all_game_injections(self) -> dict[str, Any]:
        """把上一次「清除所有第三方注入」搬走的东西**原样放回**（按备份清单）。"""
        launcher._append_log(self.config, "restore all game injections requested from UI")
        from . import game_clean

        try:
            result = game_clean.restore(
                self.config, log=lambda message: launcher._append_log(self.config, message))
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"restore all game injections failed: {exc}")
            raise
        return result

    def game_backups(self) -> dict[str, Any]:
        """列出游戏目录备份（给"撤销清除"挑用；也用于排查"备份在哪"）。"""
        from . import game_clean

        try:
            return {"ok": True, "backups": game_clean.list_backups(self.config)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc), "backups": []}

    def clean_game_injections(self) -> dict[str, Any]:
        """Park loader proxies next to the game and restore the original module."""
        launcher._append_log(self.config, "clean game dir injections requested from UI")
        try:
            result = reshade_integration.disable_game_dir_injections(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"clean game injections failed: {exc}")
            raise
        for item in result.get("disabled", []):
            launcher._append_log(self.config, f"game injection disabled: {item}")
        for item in result.get("restored", []):
            launcher._append_log(self.config, f"game module restored: {item}")
        for item in result.get("plugins", []):
            launcher._append_log(self.config, f"plugin payload disabled: {item}")
        return result

    def restore_game_injections(self) -> dict[str, Any]:
        """Undo :meth:`clean_game_injections` from its manifest."""
        launcher._append_log(self.config, "restore game dir injections requested from UI")
        try:
            return reshade_integration.restore_game_dir_injections(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"restore game injections failed: {exc}")
            raise


    def rollback(self) -> dict[str, Any]:
        import shutil

        actions = []
        errors = []
        warnings = []
        managed = self.config.managed_mods_path
        try:
            actions.extend(f"removed {item}" for item in activation.cleanup_staging(
                self.config.staging_mods_path, self.config.library_path))
        except OSError as exc:
            errors.append(f"remove managed staging failed: {exc}")
        if managed.exists():
            try:
                shutil.rmtree(managed)
                actions.append(f"removed {managed}")
            except OSError as exc:
                errors.append(f"remove managed staging failed: {exc}")
        # ⚠️ `.mc.bak` 家族统一还原（2026-10-04）：原来这里只处理 `d3dx_user.ini` 的
        # `.mc.bak`，而 EFMI 的 `d3dx.ini.mc.bak`、两份 `ReShade.ini.mc.bak`、
        # `user_ini_path.txt.mc.bak` **没有任何还原创口**（用户只能在资源管理器里翻出来改名）。
        # 现在交给 `launcher.restore_ini_backups()`（它枚举我们写过的那些 ini）。
        try:
            ini_restore = launcher.restore_ini_backups(self.config)
            actions.extend(ini_restore.get("actions") or [])
            warnings.extend(ini_restore.get("warnings") or [])
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"还原 ini 备份失败: {exc}")
        backup = self.config.user_ini_path.with_suffix(self.config.user_ini_path.suffix + ".mc.bak")
        if backup.is_file():
            try:
                shutil.copy2(backup, self.config.user_ini_path)
                actions.append(f"restored {self.config.user_ini_path}")
            except OSError as exc:
                errors.append(f"restore d3dx_user.ini failed: {exc}")
        xxmi = launcher.restore_xxmi_extra_libraries(self.config)
        if xxmi.get("ok"):
            actions.append(f"restored {xxmi.get('config_path')}")
        else:
            warnings.append(str(xxmi.get("message")))
        integration = reshade_integration.remove_existing_reshade(self.config)
        actions.extend(f"removed {path}" for path in integration.get("removed", []))
        actions.extend(f"restored {path}" for path in integration.get("restored", []))
        safe = launcher.restore_anti_cheat_safe_mode(self.config)
        actions.extend(safe.get("actions", []))
        warnings.extend(safe.get("warnings", []))
        return {"ok": not errors, "actions": actions, "warnings": warnings, "errors": errors}

    def open_path(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            return {"ok": False, "message": f"path does not exist: {target}"}
        # 2026-10-01 修（⑪）：前端传什么就打开什么，而 Windows 上 `os.startfile`
        # 对 exe/bat/lnk 是**执行** —— 一旦页面里被注入脚本，就是"任意代码执行"。
        # 现在只允许打开本程序自己的目录（runtime / 配置目录 / Mod 库）与游戏目录，
        # 并且**不直接运行**可执行文件（要跑什么请用对应功能按钮）。
        exec_suffixes = (".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".msi", ".lnk", ".scr")

        allowed = [self.config.runtime_path, self.config.base_dir, self.config.library_path]
        game_dir = reshade_integration.detect_game_dir(self.config)
        if game_dir is not None:
            allowed.append(game_dir)
        if not any(fsutil.is_within(root, target) for root in allowed):
            return {"ok": False, "message": f"出于安全考虑，只允许打开本程序自己的目录：{target}"}
        if target.is_file() and target.suffix.lower() in exec_suffixes:
            return {"ok": False,
                    "message": f"出于安全考虑，不直接运行可执行文件：{target.name}（请用对应功能按钮）"}
        # 全程不允许出现 cmd / 控制台黑窗（用户硬要求）：Popen 也要带 CREATE_NO_WINDOW。
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if sys.platform.startswith("win"):
            if target.is_dir():
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", "/select,", str(target)],
                                 creationflags=creationflags)  # noqa: S603,S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)], creationflags=creationflags)  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(target)], creationflags=creationflags)  # noqa: S603,S607
        return {"ok": True, "path": str(target)}

    def log(self) -> dict[str, Any]:
        return {
            "library": str(self.config.library_path),
            "staging": str(self.config.staging_mods_path),
            "runtime": str(self.config.runtime_path),
            "controller": str(self.config.controller_dir),
            "reshade": str(self.config.reshade_runtime_path),
        }
