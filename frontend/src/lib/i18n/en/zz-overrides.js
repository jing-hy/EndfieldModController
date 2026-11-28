// SPDX-License-Identifier: AGPL-3.0-only
// 跨片段同名键的最终口径（glob 按文件名排序合并，本文件 zz- 前缀最后加载 ⇒ 覆盖前面的同名值）。
// 各页面片段由不同人/子任务并行翻译，个别通用词给过不同英文；这里统一一次，避免同一界面出现两种说法。
export default {
  // 通用词
  "下载": "Downloads",
  "皮肤 Mod": "Outfit Mods",
  "未知原因": "Unknown reason",
  "没能装好": "Installation failed",
  "VC++ 运行库已就绪": "The VC++ runtime is ready",
  "个": "\u200b",
  "个 Mod": "mods",
  "有": "There are",
  "还有": "Still",
  "…另有": "…plus",
  "运行日志": "Runtime log",
  "失败": "Failed",
  "打不开这个位置": "Couldn't open this location",
  "打不开下载目录": "Couldn't open the download folder",
  "移到「辅助 Mod」": "Move to Assist Mods",
  "问题反馈": "Report an issue",
  "**它应该解压到**（把解压出来的 Mod 文件夹放进这里）：": "**It should be extracted to** (put the extracted Mod folder here):",
  // 重置/清空流程（三句提示取设置页版本）
  "会依次做三件事：": "Three steps run in order:",
  "① 从备份区还原终末地本体（没做过净化就跳过）；": "① Restore the Endfield game files from the backup area (skipped if the game was never cleaned);",
  "② 清掉 runtime 与 assets，然后重新下载并展开；": "② Clear runtime and assets, then download and unpack them again;",
  "③ 跳到「下载」页开始一键下载。": "③ Jump to the Downloads page and start the one-click download.",
  "清完到装好之间，组件列表会先变空，属于正常现象。": "Between clearing and reinstalling the component list is empty; that is normal.",
  "已清空 runtime 与 assets，正在跳到下载页重新下载…": "runtime and assets cleared; jumping to Downloads to re-download…",
  "点击检查程序更新": "Click to check for updates",
  "浏览": "Browse",
  "自动（按当前网络决定）": "Auto (based on current network)",
  // 中文原样恢复用到的跨片段键
  "当前是": "This is the",
  "轻量版": "Lite edition",
  "个可更新": "updates available",
};