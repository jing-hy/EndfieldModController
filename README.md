<!-- SPDX-License-Identifier: AGPL-3.0-only -->
<div align="center">

<h1>EndfieldModController</h1>

<p>《明日方舟：终末地》的一站式 Mod 管理器 —— 把 <b>DLSS5 神经渲染 + 第一人称视角 + 服装 Mod +
物理效果 + 摆姿 / MMD 播放</b> 统一到一次「一键启动」里，运行环境从零自动装好，<b>零配置启动即用</b>。</p>

<p>
  <a href="https://www.python.org/"><img alt="Python 3" src="https://img.shields.io/badge/Python-3-3776AB?logo=python&amp;logoColor=white"></a>
  <a href="https://learn.microsoft.com/windows/"><img alt="Windows 10 / 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&amp;logoColor=white"></a>
  <a href="https://github.com/jing-hy/EndfieldModController/releases"><img alt="最新版本" src="https://img.shields.io/github/v/release/jing-hy/EndfieldModController?label=Release&amp;color=f0b429&amp;logo=github"></a>
  <a href="LICENSE"><img alt="AGPL-3.0-only 许可" src="https://img.shields.io/github/license/jing-hy/EndfieldModController?label=License&amp;color=3DA639"></a>
</p>

<p>Windows 桌面程序，单文件 exe。当前版本 <b>1.6.4</b> —— <a href="https://github.com/jing-hy/EndfieldModController/releases">下载最新版</a></p>

<p>🌐 中文 | <a href="README.en.md">English</a></p>

<p>📖 安装、页面用法、逐项排查 → <b><a href="docs/README.detailed.md">详细文档</a></b><br>
🆕 这个版本改了什么 → <b><a href="RELEASE_NOTES.md">更新说明</a></b><br>
🛠 想改代码 / 提 PR → <b><a href="CONTRIBUTING.md">维护者指南</a></b></p>

</div>

---

## 亮点

- **一次「一键启动」**：补齐运行环境 → 维护注入库 → 初始化自检 → 拉起注入器；缺什么自动补，慢的时候能看见它在干活。
- **Mod 库**：压缩包拖进来即导入，自动识别角色（中文名 / 昵称 / 英文代号 / 拼音），同角色自动互斥防崩，新导入的 Mod 自动整份备份（只增不减）。
- **Mod 商城 + 下载**：内置香蕉网（GameBanana）浏览 / 搜索 / 详情与一键下载；下载在后台进行、可随时追加，下完自动入库。
- **游戏内统一面板**：进游戏按 `Home` → ModeController 页，多个 Mod 抢同一个键时从面板点就不会按错（仅完整版）。
- **崩溃归因与游戏目录净化**：崩了能分清资源冲突与其它原因；游戏目录里的第三方注入物先备份再移走，随时一键还原。
- **不折腾**：不改游戏本体、不内置 Mod、不改任何第三方组件；配置与数据就在 exe 旁边，整个文件夹拷走即可换机。
- **两个版本**：**完整版**（DLSS5 + 第一人称 + 服装 Mod）与 **轻量版**（完全不含 ReShade，只保留服装 Mod / 摇乳 / 摆姿 / 商城下载），同目录可互换。

## 选哪个版本？

| 你的情况 | 选这个 |
| --- | --- |
| 想要 **DLSS5 神经渲染 / 超分**、第一人称视角、游戏内统一面板 | **完整版** `EndfieldModController.exe` |
| 只玩**服装 Mod**（换装）+ 摇乳 + 摆姿 + 商城下载；不想让 ReShade 碰游戏 | **轻量版** `EndfieldModController-Lite.exe` |
| 游戏一开就崩 / 收到反作弊警告 / 想先把 ReShade 这条链排除掉 | **轻量版**（完全不含 ReShade：不下载、不安装、不注入；游戏目录里已有的 ReShade 残留会被移走，有备份、可还原） |
| 不确定选哪个 | 先用**完整版**；觉得 ReShade 那一套用不上，随时换轻量版 |

两版**共用同一份数据根**（`config.json` / `runtime\` / `library\`）—— 两个 exe 放同一个目录里互换即可，Mod 库、备份、下载记录都不用重来。

## 第一次使用

1. 到 [Release](https://github.com/jing-hy/EndfieldModController/releases) 下载 exe：`EndfieldModController.exe`（完整版）或 `EndfieldModController-Lite.exe`（轻量版）。
2. 放到**你有写权限的普通目录**（别放 `Program Files`、别放临时目录），双击。
3. 点「**一键启动**」。首次会自动装好运行环境；若提示"请再点一次"，照提示来即可。

之后进游戏：完整版里 DLSS5 不需要手动配置，看 ReShade 面板里的「成功NR帧」涨起来就是生效了；轻量版没有 DLSS5 这一档，服装 Mod 直接生效。首次启动有一次分步引导。

## 日常速览

- **Mod 库**：拖入压缩包 → 勾选（同角色互斥）→「生成控制器」。
- **商城 / 下载**：逛商城、加入下载；下载在后台跑，下完入库的会进「已下载」。
- **启动**：大号「一键启动」+ 各插件开关 + 运行日志。
- **设置**：左下角齿轮 → 通用 / 外观 / 路径 / 下载 / Web 服务 / 维护 / 调试 / 关于；语言（中文 / English）在「通用」。

## 常见问题

**Q：DLSS5 开关默认关 / 打不开？** 需要 **RTX 20 系及以上**（没有 tensor core 的显卡上它一帧也出不来，所以程序默认关掉）。RTX 20/30/40/50 会自动准备对应运行库。

**Q：游戏崩了 / 闪退？** 程序会生成崩溃包并给归因：资源冲突会直接列出是哪两个 Mod，去库关掉一个再启动即可；其它原因把崩溃包发到 Issues。

**Q：装了很多 Mod 没生效？** 先确认对应开关（服装 Mod / 物理效果 / DLSS5 各自独立）；同一角色只保留一个 Mod，勾选后记得「生成控制器」。

**Q：自检老说某几个文件缺失，补上又缺？** 多半是安全软件隔离。程序会弹窗告诉你**具体是哪个文件**、该把哪个目录加入白名单。

**Q：想用自己那份注入器环境？** 设置 → 路径 指过去，并关掉「使用内置运行环境」。

## 第三方组件与许可

本程序**只做分发与编排**，不修改任何组件源码，版权归各自作者：XXMI Launcher / XXMI Libraries / EFMI（MIT）、3DMigoto（MIT）、ReShade（BSD-3，仅完整版）、RenoDX / Endfield Enhancer（MIT）、iMMERSE（MIT）、SecondaryMotion、Endfield Poser（AGPL-3.0，不随 Release 分发）、NVIDIA NGX 运行库与社区 DLSS NR 运行库变体（详见[详细文档](docs/README.detailed.md)）。

本项目自身为 **AGPL-3.0-only**，条款见 [LICENSE](LICENSE)。Copyright (c) 2026 jing-hy。

## 免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**。
- 程序只读写游戏目录里的**注入类文件**，一律先备份、可一键还原；不会修改游戏本体、资源与存档。

## 反馈

设置 → 维护 →「导出诊断包」可一键打包日志与设备信息；到 [Issues](https://github.com/jing-hy/EndfieldModController/issues) 发帖或加 QQ 群 **1045239747**（验证答案 **jing_hy**）。请附上**现象**（什么时候、点了什么、看到什么）。

---

> 安装步骤、目录结构、逐项排查 → **[详细文档](docs/README.detailed.md)**　|　English → **[README.en.md](README.en.md)**　|　本版全部新功能 → **[RELEASE_NOTES.md](RELEASE_NOTES.md)**
