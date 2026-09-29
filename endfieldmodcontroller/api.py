"""Backend API exposed to the PyWebview frontend."""
from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from . import activation, core, dependencies, diagnostics, dlss5_fetcher, integrity, launcher, reshade, reshade_integration, runtime_assets, runtime_deps, selfupdate
from .config import AppConfig, auto_detect_migoto_loader, auto_detect_official_launcher, auto_detect_xxmi, cached_detect


class EndfieldModControllerApi:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config = AppConfig.load(config_path)
        self.config.ensure_dirs()
        self._mods_cache = None
        self._dep_task: dict[str, Any] | None = None
        # 把用户的下载加速/线路偏好装进 fastnet（只在下载时生效，用完即放）
        try:
            from . import fastnet

            fastnet.set_policy(getattr(self.config, "download_boost", "auto"))
            fastnet.set_line_mode(getattr(self.config, "download_line", "auto"))
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
        self._ui_ready = threading.Event()
        threading.Thread(target=self._warm_up, name="mc-warm-up", daemon=True).start()

    def ui_ready(self) -> dict[str, Any]:
        """前端首屏渲染完成后调用：这时才允许后台开始全盘探测。"""
        self._ui_ready.set()
        return {"ok": True}

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

    def log_frontend_error(self, message: str) -> dict[str, Any]:
        """接收前端 JS 错误，写进控制器日志（前端崩了也能在后端看到原因）。"""
        from . import diagnostics

        diagnostics.log_event(self.config, f"前端错误: {message}"[:2000], category="ui")
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

    def collect_crash_report(self) -> dict[str, Any]:
        """立刻收集一次崩溃现场并写成报告（不等游戏退出）。"""
        from . import crashwatch

        evidence = crashwatch.collect_evidence(self.config)
        path = crashwatch.write_report(self.config, evidence)
        return {
            "ok": True,
            "path": str(path),
            "crashed": bool(evidence.get("crash_sight")),
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
                "status": (f"v{local} 已安装" if state["manager_exists"]
                           else "未安装（点上方「自动安装/更新」会从官方仓库拉取并装好）"),
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

    def _json(self, data: Any) -> Any:
        return data

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
        from . import diagnostics, secondary_motion

        # 留痕：用来判断前端是否真的完成了初始化（界面空白时先看这几行有没有）
        diagnostics.log_event(self.config, "UI 调用 get_state()", category="ui")
        mods = self._mods()
        # **不扫盘**：本方法跑在 GUI 线程上，扫盘会把窗口渲染一起冻住（详见
        # reshade_integration.detect_game_dir 的注释）。从零启动时这里返回 None，
        # 后台预热完成后前端会自动再刷一次，那时就能经 official_launcher 推断出来。
        game_dir = reshade_integration.detect_game_dir(self.config, allow_scan=False)
        render_api = reshade_integration.detect_render_api(game_dir) if game_dir is not None else "unknown"
        return {
            "config": self.config.to_dict(),
            "mods": [m.to_dict(include_actions=False) for m in mods],
            "dependency_report": self._dependency_report(),
            "render_api": render_api,
            "controller_ready": (self.config.controller_dir / "controller.ini").is_file(),
            "reshade_addon_ready": (self.config.reshade_runtime_path / "Addons" / "endfieldmodcontroller.addon").is_file(),
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
        }
    def save_config(self, data: dict[str, Any]) -> dict[str, Any]:
        self._invalidate_mods()
        known = set(self.config.to_dict().keys())
        for key, value in data.items():
            if key in known:
                setattr(self.config, key, value)
        self.config.ensure_dirs()
        self.config.save()
        return {"ok": True, "config": self.config.to_dict()}

    # ------------------------------------------------------------------
    # library / activation
    # ------------------------------------------------------------------
    def scan(self) -> dict[str, Any]:
        from . import diagnostics

        self._invalidate_mods()
        mods = self._mods()
        diagnostics.log_event(self.config, f"UI 调用 scan() -> {len(mods)} 个 Mod", category="ui")
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
        # active_ids 为 None 时沿用当前选择，避免无参调用（CLI / 自检）把选择清空。
        # 但**空列表不能直接传给 stage_and_prepare**：activation 里空列表语义是
        # 「全部激活」，会把 library 里所有 Mod 都 stage 成 MC_*（同角色重复 → 崩游戏）。
        if active_ids is None:
            active_ids = list(self.config.selected_mods or [])
        if not active_ids:
            launcher._append_log(self.config, "未选择任何 Mod，跳过 staging")
            return {
                "activation": {"active": [], "report": "skipped"},
                "patch_count": 0,
                "action_count": 0,
                "controller_dir": str(self.config.controller_dir),
                "reshade_dir": "",
                "user_ini_path": str(self.config.user_ini_path),
                "reshade_addon": "",
            }
        result = activation.stage_and_prepare(
            self.config.library_path,
            self.config.staging_mods_path,
            self.config.runtime_path,
            selected_ids=active_ids,
        )
        self.config.selected_mods = list(active_ids)
        self.config.save()
        reshade_info = launcher.prepare_reshade_runtime(self.config, Path(result["controller_dir"]))
        launcher._append_log(self.config, f"prepare complete: actions={len(result['actions_manifest']['actions'])} patches={result['patch_count']}")
        return {
            "activation": result["activation"],
            "patch_count": result["patch_count"],
            "action_count": len(result["actions_manifest"]["actions"]),
            "controller_dir": result["controller_dir"],
            "activation_reshade_dir": result["reshade_dir"],
            "user_ini_path": result["user_ini_path"],
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
                    results = runtime_deps.ensure_all(self.config, progress)
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
            # 只把"当前这一项内部的字节进度"并进总百分比，量纲保持一致（项 → 项）
            task["percent"] = min(99.0, (done + min(max(inner, 0.0), 1.0)) / total_items * 100.0)
            if expected:
                task["message"] = f"{key}: {received / 1048576:.1f}/{expected / 1048576:.1f} MB"
            else:
                task["message"] = f"{key}: 下载中 {received / 1048576:.1f} MB"

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
        est = 0
        try:
            est += len(runtime_assets.manifest_entries(self.config)) or 1
        except Exception:  # noqa: BLE001
            est += 1
        if self.config.use_builtin_runtime:
            est += 3                                  # XXMI / XXMI-Libs / EFMI
        est += len(dlss5_fetcher.COMPONENTS)          # ReShade 底座 / DLSS5-Feeder / iMMERSE
        try:
            est += len(dependencies.load_manifest(self.config.dependency_manifest_path)) or 1
        except Exception:  # noqa: BLE001
            est += 1
        est += 1                                      # 乳摇（第三方工具）
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
            "percent": 0.0,
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
                    asset_count = len(runtime_assets.manifest_entries(self.config)) or 1
                except Exception:  # noqa: BLE001
                    asset_count = 1
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
                        for item in runtime_deps.ensure_all(self.config, progress, byte_progress):
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

                    ureport = updates_mod.check_updates(self.config, log=progress and None)
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
                self._dep_task["message"] = "完成"
                estimated = int(self._dep_task.get("estimated_total") or 0)
                if estimated and estimated != done_items:
                    self._dep_task["log"].append(
                        f"一键更新完成：实际 {done_items} 项，预估 {estimated} 项（预估公式待校准）"
                    )
            except Exception as exc:  # noqa: BLE001
                self._dep_task["message"] = f"失败: {exc}"
                self._dep_task["log"].append(f"失败: {exc}")
            finally:
                self._dep_task["running"] = False

        threading.Thread(target=worker, name="mc-full-update", daemon=True).start()
        return self.get_dependency_progress()

    def get_dependency_progress(self) -> dict[str, Any]:
        if self._dep_task is None:
            return {"running": False, "current": 0, "total": 0, "percent": 0.0, "message": "未开始", "log": [], "results": []}
        return dict(self._dep_task)

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
            self.config.reshade_dll = result["dll"]
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
    def choose_path(self, directory: bool = False, title: str = "选择路径") -> dict[str, Any]:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"tkinter unavailable: {exc}"}
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
            return {"ok": False, "message": str(exc)}
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

    def secondary_motion_install(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "补齐乳摇注入 requested from UI")
        return secondary_motion.ensure_injection(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )

    def secondary_motion_uninstall(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "卸载乳摇注入 requested from UI")
        return secondary_motion.remove_injection(
            self.config, log=lambda message: launcher._append_log(self.config, message)
        )

    def launch_secondary_motion(self) -> dict[str, Any]:
        from . import secondary_motion

        launcher._append_log(self.config, "启动乳摇管理器 requested from UI")
        return secondary_motion.launch_manager(self.config)

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
        """把**已经落盘**的 .zip 解压进 Mod 库，然后复用收编 + 角色归属流程。

        `import_mod_archive`（小包一次性传）与 `import_mod_finish`（大包分块传）
        都走这里，保证两条路径行为一致。
        """
        import re
        import shutil
        import zipfile

        launcher._append_log(self.config, f"导入: 开始解压 {name}（{archive_path.stat().st_size} B）")
        base = re.sub(r'[\\/:*?"<>|]', "_", Path(name).stem).strip() or "imported_mod"
        dest = self.config.library_path / base
        suffix = 1
        while dest.exists():
            suffix += 1
            dest = self.config.library_path / f"{base}_{suffix}"
        try:
            dest.mkdir(parents=True, exist_ok=True)
            root = dest.resolve()
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.namelist():
                    # 防 zip slip：任何解析后跑到目标目录之外的条目一律拒绝
                    target = (dest / member).resolve()
                    if not str(target).startswith(str(root)):
                        raise ValueError(f"压缩包里有非法路径: {member}")
                archive.extractall(dest)
        except (zipfile.BadZipFile, ValueError, OSError) as exc:
            launcher._append_log(self.config, f"导入失败（解压）: {exc}")
            shutil.rmtree(dest, ignore_errors=True)
            return {"ok": False, "message": f"解压失败：{exc}"}

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

        launcher._append_log(self.config, f"导入: 解压完成 → {dest.name}，开始收编与角色识别")
        try:
            synced = self.import_manual_mods()
            # 从扫描结果里取这个新 Mod（**不管它有没有进"待确认"列表**）—— 角色被成功识别时
            # 它不会出现在 pending 里，但调用方仍然需要知道识别成了谁。
            mods = self._mods()
            target = next((m for m in mods if str(m.path).startswith(str(dest))), None)
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
            }
        launcher._append_log(self.config, f"导入: 完成 {dest.name}（识别={target.group if target else '未识别'}）")
        return {
            "ok": True,
            "name": dest.name,
            "dest": str(dest),
            "synced": synced,
            "group": (target.group if target is not None else ""),
            "confidence": (target.char_confidence if target is not None else ""),
            "candidates": (list(target.char_candidates) if target is not None else []),
            "need_confirm": bool(target is not None and target.id in pending_ids),
            "imported": info,
            "pending_total": pending.get("total", 0),
        }

    def import_mod_begin(self, file_name: str) -> dict[str, Any]:
        """开始**分块**接收拖进来的压缩包。

        为什么要分块：pywebview 的 js_api 参数走 WebView2 的消息通道，一次性把几十 MB
        的 base64 丢过去会**先卡住再闪退**（2026-10-01 用户实测：「拖 zip 进去会卡在解压
        和识别角色，然后闪退」）。改成前端每块 1 MB、逐块调用，后端追加写临时文件。
        """
        name = Path(str(file_name or "")).name
        if not name.lower().endswith(".zip"):
            return {"ok": False, "message": "目前只支持 .zip（其他格式请先解压）"}
        import time as _time

        incoming = self.config.runtime_path / "_incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        token = f"{int(_time.time())}-{os.getpid()}-{abs(hash(name)) % 100000}"
        part = incoming / f"{token}.zip.part"
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
        return {"ok": True, "token": token}

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
        if info["size"] > 600 * 1024 * 1024:
            return {"ok": False, "message": "压缩包超过 600 MB，请先解压后手动放进 Mod 库"}
        return {"ok": True, "received": info["size"]}

    def import_mod_finish(self, token: str) -> dict[str, Any]:
        """分块接收完毕：落盘完成 → 走与一次性导入完全相同的解压 + 收编流程。"""
        sessions = getattr(self, "_import_sessions", None) or {}
        info = sessions.pop(str(token), None)
        if not info:
            return {"ok": False, "message": "导入会话已失效，请重新拖入"}
        part: Path = info["path"]
        if not part.is_file() or part.stat().st_size == 0:
            return {"ok": False, "message": "没有收到文件内容"}
        try:
            return self._import_archive_file(part, str(info["name"]))
        finally:
            try:
                part.unlink()
            except OSError:
                pass

    def import_mod_archive(self, file_name: str, data_b64: str) -> dict[str, Any]:
        """把拖进界面的 `.zip` 解压进 Mod 库（**一次性传**，小包用；大包走分块接口）。

        用户需求（原话）：「如果在 Mod 库界面，能直接拖 zip 进去，然后自动解压，解析角色归属」。

        为什么走 base64：pywebview 拿不到拖放文件的**本地路径**（WebView2 沙箱里
        `File.path` 不可用），所以前端用 `FileReader` 读出内容再传过来。为避免超大包
        把内存和调用参数撑爆，超过 `max_bytes` 直接拒绝并提示改用文件选择。
        """
        import base64

        name = Path(str(file_name or "")).name
        if not name.lower().endswith(".zip"):
            return {"ok": False, "message": "目前只支持 .zip（其他格式请先解压）"}
        max_bytes = 300 * 1024 * 1024
        try:
            blob = base64.b64decode(data_b64 or "", validate=False)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": f"数据解码失败：{exc}"}
        if not blob:
            return {"ok": False, "message": "没有收到文件内容"}
        if len(blob) > max_bytes:
            return {"ok": False,
                    "message": f"压缩包太大（{len(blob) / 1048576:.1f} MB），"
                               f"超过 {max_bytes // 1048576} MB，请先解压后手动放到 Mod 库"}

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
                })
        return {"pending": pending, "total": len(pending), "known": self.known_characters()}

    def set_mod_character(self, mod_id: str, character: str) -> dict[str, Any]:
        """把用户选定的角色写进该 Mod 的 `mod.meta.json`，此后扫描即为高置信。"""
        character = (character or "").strip()
        if not character:
            return {"ok": False, "message": "角色名不能为空"}
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

    def check_app_update(self, use_cache: bool = True) -> dict[str, Any]:
        """对比 GitHub release 的 tag 与本机版本号。"""
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
                    if not total:
                        return
                    task["percent"] = min(99.0, done * 100.0 / total)
                    task["message"] = (f"下载 v{latest}：{done // 1048576}/"
                                       f"{max(total // 1048576, 1)} MB")

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
            return game_clean.audit(self.config)
        except Exception as exc:  # noqa: BLE001
            launcher._append_log(self.config, f"game clean audit failed: {exc}")
            return {"ok": False, "message": str(exc), "findings": []}

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
            actions.extend(f"removed {item}" for item in activation.cleanup_staging(self.config.staging_mods_path))
        except OSError as exc:
            errors.append(f"remove managed staging failed: {exc}")
        if managed.exists():
            try:
                shutil.rmtree(managed)
                actions.append(f"removed {managed}")
            except OSError as exc:
                errors.append(f"remove managed staging failed: {exc}")
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

        def _under(candidate: Path, root: Path) -> bool:
            try:
                candidate.relative_to(root.resolve())
                return True
            except (ValueError, OSError):
                return False

        allowed = [self.config.runtime_path, self.config.base_dir, self.config.library_path]
        game_dir = reshade_integration.detect_game_dir(self.config)
        if game_dir is not None:
            allowed.append(game_dir)
        if not any(_under(target, root) for root in allowed):
            return {"ok": False, "message": f"出于安全考虑，只允许打开本程序自己的目录：{target}"}
        if target.is_file() and target.suffix.lower() in exec_suffixes:
            return {"ok": False,
                    "message": f"出于安全考虑，不直接运行可执行文件：{target.name}（请用对应功能按钮）"}
        if sys.platform.startswith("win"):
            if target.is_dir():
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603,S607
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(target)])  # noqa: S603,S607
        return {"ok": True, "path": str(target)}

    def log(self) -> dict[str, Any]:
        return {
            "library": str(self.config.library_path),
            "staging": str(self.config.staging_mods_path),
            "runtime": str(self.config.runtime_path),
            "controller": str(self.config.controller_dir),
            "reshade": str(self.config.reshade_runtime_path),
        }
