// 英文词典片段：lib/ 下的公共模块（全局弹窗、拖放导入 Mod、VC++ 运行库、UI 自动化通道）。
// 约定：key = 中文原文，value = 英文；新增片段放在 lib/i18n/en/ 下，i18n.js 会自动合并。
export default {
  // 全局弹窗按钮（dialog.js 的默认值）
  "确定": "OK",
  "取消": "Cancel",
  "知道了": "Got it",

  // 拖放导入 Mod（importMod.js）
  "读取失败": "Read failed",
  "这个格式不能自动导入": "This file type cannot be imported automatically",
  "拖进来的是：": "Dropped file: ",
  "程序只能自动解压 .zip / .7z / .rar。": "The app can only auto-extract .zip / .7z / .rar.",
  "**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：": "**It should be extracted to** (put the extracted Mod folder here):",
  "（Mod 库目录，见设置页「工作区与 Mod 库」）": "(Mod library folder — see Settings › Workspace & Mod Library)",
  "手动做法：把它解压，得到里面的 Mod 文件夹": "To do it manually: extract it and take the Mod folder inside",
  "（如果解压出来套了好几层，保留最外层那一层），整个放进上面的目录，": " (if it unpacks into several nested layers, keep the outermost one), then put the whole folder into the directory above,",
  "再回界面点「重新扫描」。": " then come back here and click “Rescan”.",
  "准备导入": "Preparing to import",
  "导入 Mod": "Import Mod",
  "导入失败": "Import failed",
  "传输失败": "Transfer failed",
  "正在上传": "Uploading",
  "正在解压并识别角色": "Extracting and detecting character",
  "这个 Mod 归到哪个角色？": "Which character does this Mod belong to?",
  "已导入「": "Imported “",
  "」，但没看出属于哪个角色。": "”, but could not tell which character it belongs to.",
  "去 Mod 库页点它的「⋯ → 更换归属」就能设定。": "Open the Mod Library, click “⋯ → Change owner” on it, and set it there.",
  "」，识别为「": "”, recognized as “",
  "」。": "”.",
  // 句中分隔符（拼接变量时单独取）
  "：": ": ",
  "（": " (",
  "）": ")",

  // 缺 VC++ 运行库（vcRuntime.js）
  "缺少 VC++ 运行库 —— 建议安装": "VC++ Runtime Missing — Installation Recommended",
  "ReShade 的插件（DLSS5 喂帧组件）依赖 VC++ 运行库，缺了它这些功能起不来。": "ReShade plugins (the DLSS5 frame-feed component) require the VC++ runtime; without it those features will not start.",
  "现在装的话：从**微软官方**下载约 24 MB 并静默安装（来源 aka.ms，国内可直连），": "Install now: download about 24 MB from the **official Microsoft site** and install it silently (source: aka.ms, reachable from mainland China),",
  "装完会把版本号报给你。跳过也能照常启动，只是那些功能可能仍然不工作。": "The installed version is reported when it finishes. Skipping is fine too: the app still launches normally, those features may just keep not working.",
  "安装（推荐）": "Install (recommended)",
  "跳过": "Skip",
  "正在下载并安装 VC++ 运行库…（约 24 MB，安装过程是静默的）": "Downloading and installing the VC++ runtime… (about 24 MB; the install runs silently)",
  "没能装好": "Install did not finish",
  "未知原因": "Unknown reason",
  "VC++ 运行库已就绪": "VC++ runtime is ready",

  // UI 自动化 / 无障碍通道（uiAutomation.js，错误文案会经 API 交回给调用方）
  "找不到元素：": "Element not found: ",
  "（先用 GET /state 取快照）": " (call GET /state for a snapshot first)",
  "不认识的动作：": "Unknown action: ",
  "（支持 click / set / value / type / scroll / scroll-by / focus）": " (supported: click / set / value / type / scroll / scroll-by / focus)",
  "执行失败：": "Action failed: ",
  "不认识的指令：": "Unknown command: ",
};
