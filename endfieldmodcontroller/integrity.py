"""Runtime integrity checks and repair for the launch flow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import activation, reshade_integration, runtime_deps
from .config import AppConfig


@dataclass
class Check:
    key: str
    ok: bool
    path: str
    message: str
    critical: bool = True
    # 「缺下载」标记（2026-10-04 加）：这一项缺失，但**有公开上游/依赖页能联网补上**。
    # 前端据此引导用户去「依赖」页下载，而不是显示一句"修不好"就没下文（用户原话：
    # 「**要是缺下载，应该跳转到依赖进行下载**」）。
    downloadable: bool = False


# 这些 key 前缀对应的缺失项，**依赖页的「一键下载依赖」能补**
# （内置 XXMI / XXMI Libraries / EFMI —— 与 dlss5 那些有公开上游的组件一起构成
#  `needs_download` 的判据）。
_DEP_DOWNLOADABLE_PREFIXES = ("xxmi_launcher", "xxmi_root", "xxmi_libs_", "efmi_")


def _downloadable_names() -> set[str]:
    """有公开上游的文件名（小写），判据委托给 `dlss5_fetcher.COMPONENTS`。"""
    try:
        from . import dlss5_fetcher

        return dlss5_fetcher.downloadable_file_names()
    except Exception:  # noqa: BLE001 —— 拿不到判据就当"不可下载"，退回原来的行为
        return set()


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def xxmi_root(config: AppConfig) -> Path | None:
    if config.use_builtin_runtime:
        return config.builtin_runtime_path / "XXMI"
    launcher = config.xxmi_launcher_path
    if launcher is None or not launcher.is_file():
        return None
    candidates = [
        launcher.parent.parent.parent,
        launcher.parent.parent,
        launcher.parent,
    ]
    for candidate in candidates:
        if (candidate / "Resources" / "Bin").is_dir() or (candidate / "EFMI").is_dir():
            return candidate
    return None


def check_integrity(config: AppConfig) -> dict:
    checks: list[Check] = []
    downloadable_names = _downloadable_names()

    def add(key: str, path: Path, ok: bool, message: str, critical: bool = True) -> None:
        # 「缺下载」判据（两条取并集）：① key 属于依赖页能补的内置组件；
        # ② 文件名落在有公开上游的组件清单里（ReShade 底座 / dlss5-feed / iMMERSE…）。
        downloadable = bool(not ok) and (
            key.startswith(_DEP_DOWNLOADABLE_PREFIXES)
            or Path(str(path)).name.lower() in downloadable_names
        )
        checks.append(Check(key, bool(ok), str(path), message, critical, downloadable))

    launcher = config.xxmi_launcher_path
    add("xxmi_launcher", launcher or Path("<unset>"), launcher is not None and launcher.is_file(), "XXMI Launcher.exe")

    root = xxmi_root(config)
    if root is None:
        checks.append(Check("xxmi_root", False, "<unknown>", "无法定位 XXMI 根目录"))
    else:
        for name in ("3dmloader.dll", "d3d11.dll", "d3dcompiler_47.dll"):
            path = root / "Resources" / "Packages" / "XXMI" / name
            add(f"xxmi_libs_{name}", path, path.is_file(), f"XXMI Libraries / {name}")
        efmi_root = root / "EFMI"
        add("efmi_main", efmi_root / "Core" / "EFMI" / "main.ini", (efmi_root / "Core" / "EFMI" / "main.ini").is_file(), "EFMI Core / main.ini")
        add("efmi_d3dx", efmi_root / "d3dx.ini", (efmi_root / "d3dx.ini").is_file(), "EFMI d3dx.ini")
        # ⚠️⚠️ **这一项要认「实际会 stage 到哪」，而不是「内置那份装没装」**
        #（2026-10-03 反馈：`use_builtin_runtime=true` 但 `staging_mods_dir` 指向外部 XXMI
        #  ⇒ 检查内置路径永远 missing ⇒ `launch failed: 完整性检查失败: EFMI Mods directory`
        #  ⇒ **启动被彻底拦死**。而就算把内置目录建出来，Mod 也进不了游戏 ——
        #  游戏读的是外部那份）。
        # `staging_mods_path` 是 `activation`/`launcher` 真正使用的同一个值，以它为准。
        staging_mods = config.staging_mods_path
        add("efmi_mods", staging_mods, staging_mods.is_dir(), "EFMI Mods directory")

    existing_reshade = reshade_integration.detect_existing_reshade(config)
    if existing_reshade is not None:
        # 本方案不使用游戏目录 ReShade（唯一底座由 XXMI 注入），只提示，不算失败。
        add(
            "game_reshade_present",
            Path(str(existing_reshade.get("ini") or existing_reshade.get("game_dir"))),
            False,
            "游戏目录仍有 ReShade —— 建议用「清理游戏目录注入」停放，避免两个 ReShade 抢 hook",
            critical=False,
        )

    if config.dlss5_injection:
        dlss5_dll = config.dlss5_dll_path
        add("dlss5_dll", dlss5_dll, dlss5_dll.is_file(), "DLSS5 ReShade 底座 d3d12.dll")
        dlss5_ini = config.dlss5_ini_path
        add("dlss5_ini", dlss5_ini, dlss5_ini.is_file(), "DLSS5 ReShade.ini（含 [endfield-enhancer] 段）")
        enhancer = config.dlss5_enhancer_addon_path
        # ★★ **只在「第一人称视角」开着时才算必检项**（2026-10-06 修）。
        #    原来无条件判 `is_file()` —— 而关掉第一人称时这个 addon 被**搬进 `_disabled\`**，
        #    根目录自然没有它 ⇒ 被判定"缺失" ⇒ `repair_integrity()` 又把它**展开回根目录**
        #    ⇒ **每次启动都这么循环一次，开关形同虚设**。
        #    实测现场（用户 21:10 那次一键启动）：
        #      `integrity missing: dlss5_enhancer_addon -> …\renodx-endfield-enhancer.addon64`
        #      → `repair: 展开内置资产 renodx-endfield-enhancer.addon64`
        #    而 ReShade 日志显示它接着就被加载了 ⇒ 用户报「第一人称还是注入进去了」。
        #    ⚠️ 同族的还有下面的 DLSS5 神经渲染 —— 都按开关判。
        if bool(getattr(config, "firstperson_addon_enabled", True)):
            add("dlss5_enhancer_addon", enhancer, enhancer.is_file(),
                "第一人称插件 renodx-endfield-enhancer.addon64")
        efmi_dll = config.efmi_dll_path
        add("efmi_dll", efmi_dll or Path("<unset>"), efmi_dll is not None and efmi_dll.is_file(), "EFMI d3d11.dll（注入用）")

    add("controller_ini", config.controller_dir / "controller.ini", (config.controller_dir / "controller.ini").is_file(), "controller.ini")
    add("controller_actions", config.controller_dir / "actions.tsv", (config.controller_dir / "actions.tsv").is_file(), "controller actions.tsv")

    # 统一面板：只在「整合 Mod 快捷键」打开时才算必检项 —— 关着的时候没有它很正常
    # （用户在设置里明确不要面板）。
    #
    # 2026-10-01 语义修正（`hotkey_takeover` 改成**默认开启**之后必须区分两种"缺面板"）：
    #   ① **环境本来就不支持面板**（没开 ReShade 注入 / 没有 d3d12.dll 底座）→ 这时它
    #      只是"用不上"，`resolve_hotkey_takeover` 会拒绝锁键、Mod 原键照常生效，
    #      **不是故障**，不能报 critical —— 否则每个不用 xxmi_extra 注入的用户一装就报红。
    #   ② **环境支持、面板该在却不在**（addon 文件缺 / actions.tsv 缺）→ 这才会导致
    #      "键被锁死而入口不存在"，算 critical，走「修复」就能补齐。
    if getattr(config, "hotkey_takeover", False):
        status = reshade_integration.panel_status(config)
        present = bool(status["addon_present"] and status["actions_present"])
        if present:
            add("hotkey_panel", Path(status["addon"]), True,
                "统一 Mod 控制面板（整合 Mod 快捷键已打开）")
        elif status.get("possible"):
            add("hotkey_panel", Path(status["addon"]), False,
                "统一 Mod 控制面板（整合 Mod 快捷键已打开）")
        else:
            add("hotkey_panel", Path(status["addon"]), True,
                "统一 Mod 控制面板 —— 当前注入方式用不上面板，已保持 Mod 自带快捷键不被锁")

    critical_failures = [check for check in checks if check.critical and not check.ok]
    # 「要联网下载才能补齐」的那些项（缺内置组件 / 缺有公开上游的 DLSS5 组件）——
    # 前端拿它决定要不要把用户**引导到依赖页**（用户 2026-10-04 的要求）。
    needs_download = [check.key for check in checks if (not check.ok) and check.downloadable]
    return {
        "ok": not critical_failures,
        "checks": [check.__dict__ for check in checks],
        "failures": [check.__dict__ for check in critical_failures],
        "needs_download": needs_download,
        "existing_reshade": existing_reshade,
    }


def repair_integrity(config: AppConfig, log: Callable[[str], None] | None = None) -> dict:
    messages: list[str] = []

    def note(message: str) -> None:
        messages.append(message)
        if log:
            log(message)

    if config.use_builtin_runtime:
        note("重新检查/安装内置 XXMI + XXMI Libraries + EFMI")
        # ⚠️ **这里刻意不传 `force=True`**（2026-10-04 明确）：`force` 会在这一条路径上
        # **当场联网下载**几十 MB，而「修复」是在启动页点的一个按钮、旁边没有任何下载进度/日志
        # 可看 —— 用户的原话是「**要是缺下载，应该跳转到依赖进行下载**」。
        # 所以职责这样分：**「修复」只做本地自愈**（补文件、写配置、重建 staging），
        # 真正需要联网的项由 `needs_download` 标出来、由前端引导去依赖页下载
        #（那边有完整链路：线路切换、进度、可暂停、失败重试）。
        for result in runtime_deps.ensure_all(config):
            note(f"{result.key}: {result.status} {result.message}")
    else:
        note("当前使用外部 XXMI，缺失的 XXMI Libraries/EFMI 需要重新安装或切换为内置运行环境")

    # ⚠️⚠️ **Mod 暂存目录要在这里确保存在**（2026-10-03 反馈的诊断包暴露）：
    # 组件全都"up_to_date"时 `ensure_all` 整个跳过，**没有任何人去建 `Mods` 目录**，
    # 于是下一次 `check_integrity` 依旧报 `efmi_mods` missing ⇒
    # 「点多少次修复都不会好」，一键启动被**彻底拦死**。
    #
    # 按用户准则「能自动做掉的就别用提示交付」——这是个能安全自建的空目录，直接建掉。
    # 用的是 `staging_mods_path`（`activation`/`launcher` 真正使用的同一个值），
    # 所以即使配置里是"用内置开关 + 外部 staging 目录"这种混合形态，也会建在对的地方。
    try:
        staging_mods = config.staging_mods_path
        if not staging_mods.is_dir():
            staging_mods.mkdir(parents=True, exist_ok=True)
            note(f"已创建 Mod 暂存目录：{staging_mods}")
    except OSError as exc:                       # noqa: BLE001
        note(f"创建 Mod 暂存目录失败：{exc}")

    from . import launcher as launcher_mod

    # ② **XXMI 的配置文件是它首次运行时才生成的** —— 刚从包里解压出来时并不存在。
    #    不存在时下面所有写入（game_folder / extra_libraries / 签名）全部落空，用户看到
    #    的就是「EFMI d3d11.dll（注入用）缺失」，而且**点多少次「修复」都不会好**
    #    （2026-10-01 issue #6 实证：22:31~22:40 六次 repair 全是同一句
    #     「写入 XXMI 注入库失败: 找不到 XXMI Launcher Config.json」）。
    #    「一键启动」这条链路本来就有这一步（launcher.ensure_injections 的第一个动作），
    #    但「修复」以前没有 —— 两条链路的自愈能力必须一致，否则界面上的「修复」是假的。
    try:
        boot = launcher_mod.bootstrap_xxmi_config(config)
        if boot.get("created"):
            note("XXMI 还没有配置文件（它首次运行才会生成）—— 已启动一次并生成")
        elif not boot.get("ok") and boot.get("message"):
            note(f"准备 XXMI 配置文件失败: {boot['message']}")
    except Exception as exc:  # noqa: BLE001
        note(f"准备 XXMI 配置文件失败: {exc}")

    # ②.5 **XXMI 的签名密钥与 `Security.user_signature` 必须先就位** —— 与「一键启动」的
    #     `launcher.ensure_injections()`（在写任何配置**之前**调 `ensure_xxmi_signing_key`）
    #     保持一致。少了这一步，「修复」写进去的 `extra_libraries_signature` 会在 XXMI
    #     下次启动时被它自己重新生成的密钥作废 → 它弹「Failed to validate unsecure
    #     settings!」→ 用户一点 Reset，注入列表就被清空。
    #
    #     为什么"修复"链路特别容易缺这一步（2026-10-02 反馈者诊断包实证）：
    #     `bootstrap_xxmi_config()` 拉起 XXMI 生成配置后是**强杀**它的 —— XXMI 自己生成的
    #     密钥对落了盘，`user_signature` 却没来得及落盘（诊断包里 `Security.user_signature`
    #     长度 **0**，正常环境是 140）；而 `sign_xxmi_setting()` 只在**私钥文件缺失**时才补
    #     这一对，私钥已存在 → 永远补不上，用户表现为「点多少次修复都还是不行」。
    try:
        launcher_path = config.xxmi_launcher_path
        xxmi_config = (reshade_integration.xxmi_config_path(launcher_path)
                       if launcher_path is not None else None)
        if xxmi_config is not None and xxmi_config.is_file():
            key_state = launcher_mod.ensure_xxmi_signing_key(xxmi_config)
            if key_state.get("generated"):
                note(str(key_state.get("message") or "已生成 XXMI 签名密钥"))
            elif not key_state.get("ok"):
                note(f"准备 XXMI 签名密钥失败: {key_state.get('message')}")
    except Exception as exc:  # noqa: BLE001
        note(f"准备 XXMI 签名密钥失败: {exc}")

    note("重新生成控制器和 staging")
    activation.stage_and_prepare(
        config.library_path,
        config.staging_mods_path,
        config.runtime_path,
        selected_ids=config.effective_selected_mods,
        # 「修复」这条链路必须与「一键启动」完全一致（issue #6 的教训）：
        # 同样先确认面板可用再决定要不要锁 Mod 热键。
        hotkey_takeover=launcher_mod.resolve_hotkey_takeover(config, config.controller_dir, log=note),
        allow_same_character=bool(getattr(config, "allow_same_character_mods", False)),
        prefer_internal_dependencies=bool(
            getattr(config, "prefer_internal_dependencies", True)
        ),
    )
    try:
        panel = reshade_integration.deploy_panel(config, config.controller_dir, log=note)
        for warning in panel.get("warnings", []):
            note(f"WARN 统一面板: {warning}")
    except Exception as exc:  # noqa: BLE001
        note(f"部署统一面板失败: {exc}")

    # ③ 随包资产（assets）+ DLSS5 目录内容 + ReShade.ini + 游戏目录运行库 + 乳摇/摆姿：
    #    这些全在 `initialize.ensure_all` 里，而它以前**只有「一键启动」会调**。
    #    后果就是 issue #6 的另一半：「DLSS5 ReShade.ini（含 [endfield-enhancer] 段）缺失」
    #    在「修复」里永远补不上（资产包没下下来时更是连来源都没有）。
    try:
        from . import initialize

        report = initialize.ensure_all(config, log=note)
        for action in report.get("actions") or []:
            note(action)
        for warning in report.get("warnings") or []:
            note(f"WARN {warning}")
    except Exception as exc:  # noqa: BLE001
        note(f"补齐随包资产/运行时失败: {exc}")

    if config.dlss5_injection:
        note("重新写入 XXMI 注入库（DLSS5 d3d12.dll + EFMI d3d11.dll）")
        try:
            result = launcher_mod.configure_dlss5_injection(config, enabled=True)
            note("注入库: " + " + ".join(result.get("extra_libraries", [])))
        except Exception as exc:  # noqa: BLE001
            note(f"写入 XXMI 注入库失败: {exc}")
    return {"messages": messages, "integrity": check_integrity(config)}
