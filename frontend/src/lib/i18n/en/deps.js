// 英文词典片段：依赖页（DepsPage.vue）—— 按钮、状态卡片、导入依赖包、下载失败/完成提示弹窗。
// 约定：key = 中文原文，value = 英文；新增片段放在 lib/i18n/en/ 下，i18n.js 会自动合并。
export default {
  // ---- 顶部按钮 / 状态卡片 -------------------------------------------------
  "重新扫描": "Rescan",
  "检查并补齐": "Check and fill in",
  "检查状态（不下载）": "Check status (no download)",
  "下载并补齐组件": "Download and complete components",
  "导入依赖包…": "Import dependency bundle…",
  "导入离线依赖包（deps-bundle.zip，连不上 GitHub 时的应急包）；导入前会逐条校验清单与哈希":
    "Import the offline dependency bundle (deps-bundle.zip — a fallback for machines that can't reach GitHub); the manifest and hashes are verified item by item before import",
  "去「下载」页": "Go to Downloads",
  "已就位组件": "Components ready",
  "缺失组件": "Missing components",
  "下载进行中 · 点此查看": "Downloads running · click to view",
  "当前没有下载": "No active downloads",
  "组件状态": "Component status",
  "被引用的依赖名": "Referenced dependency names",
  "重新安装": "Reinstall",
  "下载并启用": "Download and enable",
  "更新到": "Update to",
  "最新": "latest",

  // ---- 导入依赖包 / 安装变体 -----------------------------------------------
  "没能导入依赖包": "Couldn't import the dependency bundle",
  "导入完成": "Import complete",
  "没能安装": "Couldn't install",
  "未知原因": "Unknown reason",
  "已安装": "Installed",

  // ---- 组件状态徽章（后端 status 原样送进 t()）-----------------------------
  "已就位": "Ready",
  "已是最新": "Up to date",
  "缺失": "Missing",
  "未知": "Unknown",

  // ---- 「更新到 vX」确认弹窗 -----------------------------------------------
  "更新": "Update",
  "当前：": "Current: ",
  "未装": "Not installed",
  "最新：": "Latest: ",
  "会下载并替换它。**已经是最新的其它组件会自动跳过**，不会白下。":
    "It will be downloaded and replaced. **Other components that are already up to date are skipped automatically**, so nothing is downloaded twice.",
  "点「开始更新」会跳到「下载」页，那里能看到进度与日志。":
    "Clicking \"Start update\" jumps to the Downloads page, where you can watch progress and the log.",
  "开始更新": "Start update",
  "先不更新": "Not now",
  "正在更新": "Updating",
  "开始安装/更新组件…": "Starting component install / update…",

  // ---- dry-run「检查状态」-------------------------------------------------
  "正在检查组件状态…（只检查，不下载）": "Checking component status… (check only, nothing is downloaded)",
  "检查完成（没有下载任何东西）": "Check complete (nothing was downloaded)",
  " 个：": ":",
  "没有缺失的组件。": "No missing components.",
  "有": "Found",
  " 个可以更新：": " to update:",
  "没有可更新的组件。": "No components to update.",
  "要装/要更新的话，点上面的「安装缺失依赖」或「一键安装/更新全部组件」。":
    "To install or update, use \"Install missing dependencies\" or \"Install / update all components\" above.",
  "知道了": "Got it",
  "检查失败": "Check failed",
  "已检查并补齐缺失组件": "Checked and filled in missing components",

  // ---- 「需手动解压」弹窗 --------------------------------------------------
  "个包需要你手动解压": "packages need to be extracted manually",
  "这些包程序没法自动解压（不是 zip/7z/rar，或者包本身下坏了），所以**原样留在磁盘上、没有删除**：":
    "The app can't extract these packages automatically (they're not zip/7z/rar, or the archive is corrupt), so they are **left on disk as-is and not deleted**:",
  "…另有": "…and",
  " 个": " more",
  "**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：": "**They should be extracted to** (put the extracted Mod folders here):",
  "（Mod 库目录）": "(Mod library folder)",
  "手动做法：把上面的包解压，得到里面的 Mod 文件夹（如果解压出来套了好几层，保留最外层那一层），整个放进上面的目录，再回界面点「重新扫描」。":
    "To do it manually: unpack the archives above to get the Mod folders inside (if unpacking nests several levels, keep only the outermost one), move them into the folder above, then come back and click \"Rescan\".",
  "（如果消息里说了是 CRC/损坏，那多半是**下载过程中坏了**，重新下一次即可。）":
    "(If the message mentions CRC or corruption, the download was most likely **damaged in transit** — just download it again.)",
  "打开下载目录": "Open download folder",
  "打不开下载目录": "Couldn't open the download folder",

  // ---- 下载失败 / 太慢弹窗 -------------------------------------------------
  "这个下载源连不上或太慢": "This download source is unreachable or too slow",
  "Mod 下载失败": "Mod download failed",
  "没能下下来：": "couldn't be downloaded:",
  "**香蕉网在国内直连常常只有 10 KB/s 左右**，这多半不是你或程序的问题。":
    "**Direct connections to 香蕉网 (Banana Network) from mainland China often top out around 10 KB/s** — this is usually not your fault or the app's.",
  "建议：": "Suggestions:",
  "· 开加速器 / VPN 后重试（实测能把单连接从 0.008 提到 0.129 MB/s）":
    "· Retry with a VPN / accelerator enabled (measured: a single connection went from 0.008 to 0.129 MB/s)",
  "· 或者点上面的「继续」，它会从断点接着下，已下完的部分不用重来":
    "· Or click \"Resume\" above — it continues from where it stopped, so finished parts are not downloaded again",
  "· 「设置 → 下载与网络」里可以确认「下载加速」没被关掉":
    "· Check that \"Download acceleration\" is still enabled under Settings → Downloads & Network",
  "下载失败：": "failed to download:",
  "（没有更多信息，详见右侧日志）": "(No further details — see the log on the right)",

  // ---- 暂停 / 终止 / 完成弹窗 ----------------------------------------------
  "（未命名）": "(unnamed)",
  "Mod 下载已暂停": "Mod download paused",
  "Mod 下载已终止": "Mod download stopped",
  "已停下（断点保留）。": "Paused (resume point kept).",
  "已终止（半成品已清理）。": "Stopped (partial files cleaned up).",
  "本次已经完成入库": "Successfully imported",
  "还有": "Still",
  "个没下完": "to finish",
  "点本页的「继续」会从断点接着下，已下的部分不用重来。":
    "clicking \"Resume\" on this page continues from where it stopped; parts already downloaded are not repeated.",
  "没下完的那几个可以在本页重新开始。": "You can restart the unfinished ones from this page.",
  "Mod 下载完成": "Mod download complete",
  "已下载并入库": "Downloaded and imported",
  " 个（列表已刷新）：": " (list refreshed):",
  "另有": "Additionally,",
  " 个失败，可在本页重试。": " failed — retry from this page.",
  "识别为": "recognized as",
  " 个没识别出角色（": " without a recognized character (",
  "、": ", ",
  "），去「服装 Mod / 辅助 Mod」页点它的「⋯ → 更换归属」设定。":
    "), open the Outfit Mods / Assist Mods page and use \"⋯ → Change owner\" there.",
  "需要手动解压": "Manual extraction needed",
  "：": ": ",
  " —— ": " — ",

  // ---- 安装结束 toast ------------------------------------------------------
  "安装结束，但有": "Install finished, but",
  " 项失败 —— 详情见右侧安装日志": " items failed — see the installation log on the right",
  "安装结束，仍有": "Install finished, but still",
  " 项缺失 —— 详情见右侧安装日志": " items missing — see the installation log on the right",
  "安装失败：": "Install failed: ",
  "依赖安装/更新完成": "Dependencies installed / updated",
};
