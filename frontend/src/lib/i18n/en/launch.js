// 英文词典片段：启动页（LaunchPage.vue）。
// 约定：key = 中文原文，value = 英文；lib/i18n/en/*.js 由 i18n.js 自动合并。
// 说明：以「：」结尾的 key 在英文值里带一个尾随空格，拼接变量时不会把词粘在一起；
//      「、」「：」是纯展示分隔符（列表顿号 / 组件名与版本号之间的冒号）。
export default {
  // ── 顶部按钮 / 启动进度 / 运行日志 ─────────────────────────────────────────
  "一键启动": "One-click Launch",
  "正在启动…": "Launching…",
  "热重载": "Hot reload",
  "热重载中…": "Hot reloading…",
  "运行日志": "Runtime log",
  "清空": "Clear",
  "清空启动日志": "Clear launch log",
  "保留日志": "Keep logs",
  "启动日志已清空": "Launch log cleared",
  "就绪。点「一键启动」：先跑初始化自检（缺什么补什么），再拉起 XXMI Launcher。":
    "Ready. Click \"One-click Launch\": it runs the init self-check first (filling in whatever is missing), then starts XXMI Launcher.",

  // ── 热重载 ────────────────────────────────────────────────────────────────
  "热重载：先重铺配置，再给游戏发 F10…": "Hot reload: re-applying config, then sending F10 to the game…",
  "热重载已发起": "Hot reload started",
  "热重载没成功": "Hot reload did not succeed",
  "热重载失败：": "Hot reload failed: ",

  // ── 注入开关 ──────────────────────────────────────────────────────────────
  "注入开关": "Injection switches",
  "已开启": "On",
  "已关闭": "Off",
  "（不可用）": "(unavailable)",
  "禁用所有 ReShade 注入": "Disable all ReShade injections",
  "阻止所有 ReShade 注入，能大幅提升账号安全性（风险不为零）；开启后会把已有的 ReShade 注入清理出终末地（可还原）。代价是 DLSS5 神经渲染、第一人称视角、统一管理器面板都不可用。":
    "Blocks every ReShade injection and greatly improves account safety (the risk is not zero). When on, existing ReShade injections are cleaned out of Endfield (restorable). The cost: DLSS5 neural rendering, first-person view and the unified manager panel are all unavailable.",
  "统一管理器": "Unified manager",
  "注入 ReShade 与统一管理器面板": "Injects ReShade and the unified manager panel",
  "Mod 快捷键锁定": "Mod hotkey locking",
  "把 Mod 自带快捷键锁成内部键，避免 Mod 之间抢键": "Maps Mod hotkeys to internal keys so Mods stop fighting over keys",
  "DLSS5 神经渲染": "DLSS5 neural rendering",
  "把游戏自身的 DLSS 输出替换成 DLSS5 神经渲染": "Replaces the game's own DLSS output with DLSS5 neural rendering",
  "第一人称视角": "First-person view",
  "进游戏按 F1 切换第一人称": "Press F1 in game to toggle first-person view",
  "皮肤 Mod": "Skin Mods",
  "EFMI 服装 Mod 注入（关掉后不加载任何皮肤）": "EFMI outfit Mod injection (when off, no skins are loaded)",
  "乳摇物理效果": "Jiggle physics",
  "摆姿 / MMD 播放": "Posing / MMD playback",
  "「禁用所有 ReShade 注入」开着 —— 先关掉它才能开这个":
    "\"Disable all ReShade injections\" is on — turn it off first to enable this",

  // ── 渲染 API 状态 ─────────────────────────────────────────────────────────
  "上次启动：Vulkan —— 服装 Mod 不生效，请在启动器里选 DirectX 11 启动":
    "Last launch: Vulkan — outfit Mods don't work; choose DirectX 11 in the launcher",
  "上次启动：DirectX 12 —— 服装 Mod 不生效，请在启动器里选 DirectX 11 启动":
    "Last launch: DirectX 12 — outfit Mods don't work; choose DirectX 11 in the launcher",
  "上次启动：DirectX 11": "Last launch: DirectX 11",
  "上次启动：未知（还没启动过，或读不到渲染 API）":
    "Last launch: unknown (not launched yet, or the render API can't be read)",

  // ── 启动前异常状态预警 ────────────────────────────────────────────────────
  "检测到异常状态": "Abnormal status detected",
  "异常状态": "Abnormal status",
  "详情：": "Details: ",
  "（请先读完，": "(Please read first: the button unlocks in ",
  " 秒后按钮才可点）": " s)",
  "「还原配置」= 关掉所有注入开关 + 把游戏目录的第三方文件备份移走（可恢复）":
    "\"Restore config\" = turn off all injection switches and move third-party files out of the game directory (backed up, reversible)",
  "「保持配置」= 什么都不动，只是这次不启动": "\"Keep config\" = change nothing, just skip this launch",
  "「仍然启动」= 照常启动（配置有问题的话很可能起不来）":
    "\"Launch anyway\" = launch as usual (a broken config will most likely fail to start)",
  "还原配置（推荐）": "Restore config (recommended)",
  "保持配置，不启动": "Keep config, don't launch",
  "仍然启动": "Launch anyway",
  "已按你的选择还原配置，这次不启动。": "Config restored as you chose; not launching this time.",
  "已保持配置，这次不启动。": "Config kept; not launching this time.",
  "你选择了「仍然启动」，继续。": "You chose \"Launch anyway\", continuing.",

  // ── 启动前风险确认（资源冲突 / 崩溃记忆）────────────────────────────────────
  "发现 Mod 冲突风险": "Mod conflict risk detected",
  "这套组合以前崩过": "This combo has crashed before",
  "**资源冲突**（这些 Mod 改的是同一批资源，同时开常常会让游戏崩）：":
    "**Resource conflicts** (these Mods touch the same resources; enabling them together often crashes the game):",
  "**以前崩过**（这套组合在你这台机器上留下过崩溃记录）：":
    "**Crashed before** (this combo left crash records on your machine):",
  "一组 Mod": "a group of Mods",
  "（以前崩过 ≠ 现在一定冲突；后来跑通过的话记录会被自动忽略。）":
    "(Crashed before ≠ conflicting now; if it worked afterwards the record is ignored automatically.)",
  "先去清理": "Clean up first",
  "已按提示先去清理冲突，这次不启动。": "Going to clean up the conflicts first; not launching this time.",

  // ── 文件守护 / 杀毒软件 ───────────────────────────────────────────────────
  "有文件被反复删除": "Files keep getting deleted",
  "这些关键文件被删掉过不止一次：": "These key files have been deleted more than once:",
  "（见日志）": "(see the log)",
  "**多半是杀毒软件误删**。建议把下面这个目录加进杀毒软件的白名单：":
    "**Most likely the antivirus deleted them by mistake.** Add the directory below to your antivirus whitelist:",
  "选「知道了」以后不再提醒；选「继续提醒」则会保留这条提醒。":
    "\"Got it\" stops the reminder; \"Keep reminding me\" keeps it.",
  "知道了，不再提醒": "Got it, don't remind me again",
  "继续提醒我": "Keep reminding me",
  "知道了": "Got it",
  "Windows Defender 处理过这些文件": "Windows Defender handled these files",
  "Defender 最近隔离 / 删除了本程序或游戏要用的文件：":
    "Defender recently quarantined or deleted files needed by this app or the game:",
  "缺了它们游戏可能起不来、或者装好的功能失效。点下面的按钮把它们从隔离区还原回去。":
    "Without them the game may fail to start, or installed features stop working. Click the button below to restore them from quarantine.",
  "若反复发生，可在设置里确认「自动加 Defender 白名单」是开着的（默认开）。":
    "If this keeps happening, check that \"Auto-add Defender whitelist\" is on in Settings (on by default).",
  "从隔离区还原": "Restore from quarantine",
  "已跳到「下载」页，正在开始下载…": "Switched to the Downloads page, starting the download…",
  "已还原": "Restored",
  "个文件": "files",
  "还原没成功，原始错误在日志里": "Restore failed; the original error is in the log",
  "有": "There are",
  "项需要联网下载：": "items to download: ",
  "、": ", ",
  "—— 已跳到「下载」页开始下载": "— switched to the Downloads page to start",
  "完整性检查发现": "Integrity check found",
  "项缺失，开始联网下载补齐…": "items missing, downloading them now…",

  // ── 完整性检查 / 修复 ─────────────────────────────────────────────────────
  "检查/修复完整性": "Check / repair integrity",
  "完整性检查失败": "Integrity check failed",
  "后端没有返回检查结果。": "The backend returned no check result.",
  "未知原因": "Unknown reason",
  "完整性检查：全部正常": "Integrity check: all good",
  "没有可检查的项。": "Nothing to check.",
  "完整性检查：": "Integrity check: ",
  "项缺失": "items missing",
  "其中": "Of these,",
  "项需要联网下载": "items need downloading",
  "才能补齐：": "to finish the fix:",
  "要不要现在自动修复？（**只做本地能做的**：补文件、写配置、重建 staging；需要下载的部分会引导你去「下载」页）":
    "Repair automatically now? (**Local fixes only**: restore files, write config, rebuild staging; anything that needs downloading sends you to the Downloads page)",
  "去下载页下载": "Go to Downloads page",
  "自动修复": "Auto repair",
  "先本地修复": "Fix locally first",
  "先不修": "Not now",
  "正在修复完整性…（只做本地能做的部分）": "Repairing integrity… (local fixes only)",
  "还有": "There are still",
  "项要联网下载": "items to download",
  "本地能做的都做完了；下面这些需要从网上取：":
    "Everything that can be done locally is done; these still have to come from the internet:",
  "要现在跳到「下载」页下载吗？（那边会显示线路与进度，可暂停）":
    "Jump to the Downloads page and download now? (It shows routes and progress, and can be paused)",
  "稍后自己弄": "I'll handle it later",
  "修复完成，还有": "Repair finished;",
  "项没修好": "items still failing",
  "完整性已修复": "Integrity repaired",
  "所有缺失项都已补齐。": "All missing items have been filled in.",
  "修复失败": "Repair failed",

  // ── 组件更新 ──────────────────────────────────────────────────────────────
  "个组件有新版本": "components have updates",
  "：": ": ",
  "这些组件有新版本可用：": "These components have new versions available:",
  "去「下载」页点「一键更新全部组件」就能装上（那里有进度和速度）。":
    "Go to the Downloads page and click \"Update all components\" to install them (with progress and speed).",
  "想先不管、直接启动也可以。": "You can also ignore this and launch right away.",
  "去下载页更新": "Update on Downloads page",

  // ── 一键启动的收尾判定 ────────────────────────────────────────────────────
  "启动失败：": "Launch failed: ",
  "等了 30 秒没看到终末地进程 —— 游戏没有启动":
    "No Endfield process after 30 seconds — the game did not start",
  "终末地启动后 10 秒内就退出了（启动失败）": "Endfield exited within 10 seconds of starting (launch failed)",
  "等了 10 分钟 XXMI Launcher 还开着，就不再往下判定了（它可能还在正常工作）。":
    "XXMI Launcher is still open after 10 minutes, so the check stops here (it may still be working normally).",
  "第一次启动：请再点一次": "First launch: click again",
  "终末地没有起来": "Endfield did not start",
  "看起来是第一次启动（内置组件刚装好 / 配置刚生成）。":
    "This looks like the first launch (built-in components were just installed / the config was just generated).",
  "**终末地已经起来了**，但第一次常常会起不来或很快退出。":
    "**Endfield has started**, but the first time it often fails to start or exits quickly.",
  "如果它没进游戏，再点一次「一键启动」就好。":
    "If it doesn't get into the game, just click \"One-click Launch\" again.",
  "**第一次启动有概率起不来**，再点一次通常就好了。":
    "**The first launch may well fail to start**; trying again usually works.",
  "如果连续几次都不行，去「依赖」页看运行日志和自检结果。":
    "If it keeps failing, check the runtime log and self-check results on the Dependencies page.",
  "再次启动": "Launch again",
  "先不启动": "Don't launch yet",
  "按提示再来一次一键启动…": "Running one-click launch again as prompted…",

  // ── 底部按钮 / 通用 ───────────────────────────────────────────────────────
  "启动插件界面（乳摇管理器）": "Open add-on UI (ShakingBreastManager)",
  "打开摆姿页（Poser）": "Open posing page (Poser)",
  "生成控制器": "Generate controller",
  "检查游戏目录注入": "Check game directory injections",
  "操作未完成": "Operation did not complete",
  "操作失败": "Operation failed",
  "没能改这个开关": "Couldn't change this switch",
  "开关已改，但有遗留问题": "Switch changed, but some issues remain",
  "会清空 `runtime\\logs\\launch.log`。": "This clears `runtime\\logs\\launch.log`.",
  "排查问题时日志很有用，建议**先导出一份诊断包**再清。":
    "The log is very useful when troubleshooting — export a diagnostics bundle first.",
};
