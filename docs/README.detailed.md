# EndfieldModController —— 详细文档

> 这是**详细版**：安装细节、数据与目录结构、逐项故障排查、开发与发布流程都在这里。
> 只想正常使用的话，看简略版就够了 → **[README.md](../README.md)**

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）** 以及 **乳摇（SecondaryMotion）** 统一到一次「一键启动」里，并自动维护各项注入与初始化自检。

Windows 桌面程序（Python + PyWebview），单文件 exe，**零配置启动即用**。当前版本 **0.6.0**。

> 本程序**只做编排与自检**：注入由 XXMI Launcher 完成，服装 Mod 由 EFMI 加载，神经渲染与第一人称是挂在同一个 ReShade 底座下的 addon。
> 它**不改游戏本体文件**，也不内置任何 Mod —— Mod 都是你自己放进来的。

---

## 一、它能做到什么

| 能力 | 说明 |
| --- | --- |
| **从零装好运行环境** | 首次启动自动下载并安装 XXMI Launcher、XXMI Libraries、EFMI 三个组件（Release 资产带 sha256 校验），装完写好配置 |
| **Mod 库管理** | 把 `.zip` **拖到页面任意处**即可导入；自动解压进库、尝试识别角色归属，拿不准就问你要哪个角色 |
| **同角色互斥** | 同一个角色只保留一个 Mod，避免 EFMI 同时加载两个同角色 Mod 把游戏搞崩 |
| **收编手动 Mod** | 你自己丢进 `Mods` 目录的 Mod 会被认出来、收进库并在界面勾选上 |
| **一键启动** | 维护 XXMI 的注入库（DLSS5 的 `d3d12.dll` + EFMI 的 `d3d11.dll`）、补齐缺失组件、跑完整初始化自检，然后拉起 XXMI |
| **插件开关** | DLSS5、第一人称、第三方服装 Mod、乳摇注入，都能单独开关（可逆，靠移动文件而不是删文件） |
| **DLSS5 自检** | 检查并补齐 shader 编译依赖、ReShade 标准头、纹理目录、preset 里的 technique 与运动矢量来源 —— 这几项缺任何一项都会"看起来都装了，就是不出帧" |
| **乳摇开箱可用** | 自动实例化管理器的模板文件、纠正 `enabled` 开关、并预写 `settings.json` 记住游戏目录（不再每次让你选文件夹） |
| **游戏目录净化 / 还原** | 把第三方注入物**先备份再移走**（`runtime/game_backup/…`），随时一键还原；被移走的系统模块会自动从 System32 补回 |
| **诊断与日志** | 启动日志、崩溃监视、一键导出诊断 zip（含日志、注入状态、Windows 事件、**DLSS5 现场 `dlss5-feed.log`**） |
| **崩溃归因** | 崩溃包会带 `cause.json`：**自检记录过 Mod 资源冲突时，弹窗专门提示去清冲突**（区别于其它崩溃，主按钮直接跳到 Mod 库）；同时自检会校验 `runtime\dlss5` 里的随包组件是否被别的整合包换过 |
| **启动前风险确认** | 一键启动在**拉起 XXMI 之前**先查"这套 Mod 会不会崩"：① 自检的资源冲突；② **崩溃记忆**（`runtime\_state\crash_memory.json`，记下每次崩溃时的 Mod 组合）。有风险就弹窗说清是什么冲突，由你选「仍然启动」/「先去清理，不启动」 |
| **Mod 修复 / 回滚 / 移出库（实验性）** | Mod 卡片**右下角「⋯」**：用社区修复工具（**B站 up 主 可可HXL**《终末地Mod修复工具包》v1.5）把 ini 里的资源槽位号适配当前游戏版本；**改前整份备份、可一键回滚**；删除 = 移出库（进 `runtime\backups\mod-trash`，可找回）。库页顶部还有**「一键修复所有 Mod」**（后台跑、已修过的跳过） |
| **角色表跟官网** | 角色识别用的表**每次启动后在后台非阻塞**地跟官网干员页对一次（24 小时内不重复请求）：官网上了新干员就自动更新到 `<数据根>\runtime\_state\characters.json`（**不改随包那份、社区简称不丢**）；也可手工跑 `python scripts\fetch_characters.py` 核对/更新 |
| **更新** | 检查/下载新版并自更新（下载后校验 sha256，退出后由脚本替换并重启）；组件（XXMI / EFMI / 乳摇）也能单独更新 |
| **下载兜底** | 内置轻量加速：慢/抖时临时并发分块，直连不通时临时换镜像线路 —— 按需启用、用完即放，不装证书、不改系统 |
| **摆姿 / MMD 播放（Endfield Poser）** | 从它的官方 Release 下载安装包，调用**它自己的安装向导**把文件装进游戏目录（不随包分发、不改它的包）；开关只改文件名（可逆）；状态与日志在设置页，摆姿用它自带的页面 `http://127.0.0.1:18923` |

### 本版新增（v0.6.0 相对 v0.5.0）

> 上一版（v0.5.0）做了 Endfield Poser 集成；这一版围绕**"为什么崩 / 提前拦住崩溃 / 修老 Mod"**三件事。

- **Mod 冲突有专属崩漰弹窗**：自检记录过 Mod 资源冲突时，崩溃弹窗会直接说「这次崩溃很可能由 Mod 资源冲突引起」并列出是哪两个 Mod 撞了资源，主按钮一键跳到「Mod 库」；普通崩溃保持原样。归因同时写进崩溃包的 `cause.json` 与报告正文的「归因」行。
- **一键启动前先查"这套 Mod 会不会崩"**：在**拉起 XXMI 之前**检查 ① 本次自检的资源冲突 ② **崩溃记忆**（`runtime\_state\crash_memory.json`，记下每次真崩溃时跑的是哪套 Mod；正常退出不记）。有风险就弹确认框：右侧橙色主选项「**先去清理，不启动**」（默认聚焦，按 Enter 就是它），左侧次要「仍然启动」。
- **Mod 卡片右下角「⋯」：修复 / 回滚 / 移出库**（**实验性**）：用社区修复工具（B站 up 主 **可可HXL**《终末地Mod修复工具包》v1.5，随包分发）把 ini 里的资源槽位号适配当前游戏版本。每个 Mod **先整份备份、可一键回滚**；修复全程在**临时目录**里跑，不在 Mod 库/Mods 里留下备份与日志。「删除」= 移出库到 `runtime\backups\mod-trash\<时间戳>\`（可找回）。库页顶部另有「**一键修复所有 Mod**」（后台跑、已修过的跳过）。
- **自检新增「随包组件基线校验」**：把 `runtime\dlss5` 里的实际文件与随包清单（大小 + sha256）逐项对照，并单独盯 `dlss5-feed.addon64`（**只提示、不自动覆盖**你的文件）。
- **崩溃包 / 诊断包带上 DLSS5 现场**：`dlss5-feed.log`、`dlss5-feed.cfg`、`ReShade.ini`、`ReShadePreset.ini`（诊断包另含 `mod_conflicts.json`）—— 以后发反馈不用再靠猜。
- **角色表跟官网自动更新**：每次启动后在**后台非阻塞**地跟官网干员页对一次（24 小时内不重复请求、失败静默），官方上了新干员就自动更新到 `<数据根>\runtime\_state\characters.json`（**不改随包那份**，本地补的社区简称也不会丢）。也可以手工跑 `python scripts\fetch_characters.py`。
- **依赖页乳摇那项不再显示「v 已安装」**：读不到版本号时显示「已安装（版本号读不到）」，正常时照旧显示 `v2.3.5 已安装`。
- **更正一处错误说法**：此前 README 写"`dlss5-feed.addon64` 1.18 版在终末地上不会出帧"——**实测两版都能正常出帧**（详见常见问题），已按实测更正。它是在线组件，「一键安装/更新全部组件」本来就会把它更新到上游最新版。

### 注入链（同一进程内同时生效）

```text
唯一的 ReShade 底座  runtime\dlss5\d3d12.dll（ReShade 6.8.0 Addon 版）
  ├─ renodx-dlss5-4.7_汉化.addon64      → DLSS5 神经渲染
  ├─ renodx-endfield-enhancer.addon64   → 第一人称 / 相机
  ├─ dlss5-feed.addon64                 → 给 DLSS5 喂"颜色 + 运动矢量 + 深度"
  ├─ trans-zh.addon64                   → 面板汉化
  └─ reshade-shaders\                   → DLSS5_Feed.fx、iMMERSE、ReShade 标准头
服装 Mod 引擎  EFMI\d3d11.dll
乳摇注入       游戏目录的 d3dcompiler_47.dll / vulkan-1.dll（代理）+ plugin\sbm.dll
摆姿 / MMD     同一个 d3dcompiler_47.dll 代理（加载 plugin 下所有 dll）+ plugin\poser.dll
```

XXMI Launcher 启动游戏时按「注入库」注入上表里的 DLL，注入库由本程序维护，启动页的开关就是它的快捷切换。
**一个游戏进程只能有一个 ReShade 底座**，所以不要把两个 `d3d12.dll` 同时注入。

---

## 二、运行与安装

### 方式 A：直接双击 exe（推荐）

1. 下载 `EndfieldModController.exe`（Release 里 exe 只有这一个文件，另有一个 `assets-bundle.zip`）；
2. 放到一个**你有写权限的目录**（见下方"数据根"），双击；
3. exe 的 manifest 自己要求管理员权限，会弹一次 UAC —— 点"是"。
   （XXMI Launcher 的 exe 要求管理员，非管理员启动会直接报 WinError 740，所以默认就按管理员处理。）

### 方式 B：从源码运行

```bat
pip install -r requirements.txt
run.vbs          :: 无控制台黑窗（推荐）
run.bat          :: 有依赖兜底与错误提示，但会闪一个 cmd 窗口
run.bat --cli    :: 不开界面，直接打印当前状态 JSON（调试用）
```

### ⚠ 数据根 = exe 所在目录

`config.json`、`runtime\`、`library\` 都生成在 **exe 所在目录**（源码运行时是仓库根目录）。
所以：**别把 exe 放进 `Program Files` 这类只读目录**，也别放在临时目录（清理工具会连你的 Mod 库一起删掉）。

### 首次启动会发生什么

1. **界面立刻出现**：窗口 1~3 秒内出现并显示加载页（从零启动实测 2.7 秒；窗口底色跟随主题，加载页至少显示 0.7 秒），**不存在"亮着窗口一片空白"的阶段**；全盘探测在首屏出来之后才开始，不挡界面；
2. 自动下载安装 XXMI / XXMI Libraries / EFMI；
3. XXMI 的配置是**它首次运行时自己生成**的，所以本程序会先拉起一次 XXMI 生成配置、随后关闭它，并在拉起 XXMI 之后提示：

   > 第一次启动可能失败 —— 建议再启动一次。
   > 点了 XXMI 里的 Start 之后，终末地有概率不会正常启动；如果发现游戏没开起来，**再启动一次**通常就好了。

   （提示只在"真的拉起来过 XXMI"或"还没走过首次引导"时出现一次，不会反复弹。）

4. 再点一次「一键启动」就会真正写好注入库并拉起 XXMI。

> **DLSS5 那套组件没有上游可下载**（`renodx-endfield-enhancer.addon64`、`trans-zh.addon64`、`nvngx_dlssnr.dll` 全网都没有自动可用的发布源），需要随包自备（`assets\dlss5\`）或从可用的旧环境复制到 `runtime\dlss5\`。缺了会明确提示缺哪个文件，而不是静默失败。

### DLSS5 装完直接玩，不需要手动配置

出帧所需的全部条件（ReShade shader 标准头与纹理、NGX 运行库、运动矢量来源、preset 里两个 technique 的启用与顺序）都由初始化自检自动写好、每轮校验，**不需要你进游戏点任何东西**：一键启动 → 进游戏 → 面板 `成功NR帧` 应该就开始涨。

想确认它真在工作，最直接是看 `runtime\dlss5\dlss5-feed.log`，成功时是这样：

```
################ feed: opening D3D12 session ################
[feed] NVSDK_NGX_D3D12_Init -> 0x00000001 (Success)
[feed] feature ready: 3840x2160 DLAA, flags=74 ...
[feed] frame 1 delivered (3840x2160, reset=1)
[feed] 600 frames: feed CPU 0.4x ms/frame ...
```

万一没出帧，按 FAQ「能进游戏但成功NR帧一直是 0」那三条路径排查（那里也包含"实在不行在面板里手工激活一次"的兜底做法）。

---

## 三、日常使用

### Mod 库页

- **导入**：把 `.zip` 拖进窗口 → 出现全屏提示框 → 松手即导入（仅"Mod 库"页接受拖放；拖出窗口或按 Esc 会取消提示）。
- **角色识别**：导入后按 Mod 名/ini 里的线索猜角色；不确定会弹窗让你选，也可以稍后点卡片上的"角色待确认"。
  这张角色表**只认官网**（`endfield.hypergryph.com/operator`，一手来源；第三方聚合站的译名有硬错误）：程序每次启动后在后台跟官网对一次，上新干员时自动把新角色（含官网英文代号与美术 key）并进 `<数据根>\runtime\_state\characters.json`，**本地手工补的社区简称一律保留**，也不会覆盖随包那份。想手工核对/更新就 `python scripts\fetch_characters.py`（`--write` 写运行时表，`--update-bundled` 才动随包表）。
- **每个 Mod 卡片右下角有「⋯」**：鼠标移上去就地弹出小菜单 —— **修复（实验性）** / **回滚修复** / 打开所在文件夹 / **移出 Mod 库**。已修复过的卡片上会有「✓ 已修复过」标记。库页顶部还有「一键修复所有 Mod（实验性）」。
- **勾选**：勾选即保存（同角色自动互斥）。点「生成控制器」把选择落成 EFMI 要加载的内容。
- **热键**：Mod 自带的热键会被统一接管（改成 `VK_F24`），改由本程序的面板/动作队列驱动 —— 避免 Mod 自己的按键和游戏冲突。

### 启动页

- **一键启动**：补齐组件 → 同步 XXMI 注入库 → 初始化自检 → 拉起 XXMI（不自动进游戏；进游戏由 XXMI 或「启动游戏」按钮完成）。
- **打开官方 XXMI**：只打开 XXMI 自己的界面，不动注入库。
- **强制关闭**：收掉残留的 loader / 游戏进程（**不会**在你没要求的情况下强杀正在玩的游戏）。

### 设置页

路径配置（XXMI / 游戏 / loader / 乳摇工具）、下载加速与线路、主题、单实例与游戏多开防护、是否部署新版 nvngx、依赖清单等。
`config.json` 里的键与默认值可参考 `config.example.json`（由程序默认值直接导出）。

> **关于"部署新版 nvngx"**：默认**关闭**。DLSS5 的神经渲染接口（`NVSDK_NGX_D3D12_EvaluateFeature_C`）住在 `nvngx_dlssnr.dll` 里，本程序会把它放在 `runtime\dlss5\` 供 addon 加载；游戏目录里那份 `nvngx_dlss.dll` 保持**游戏原版**即可。打开这个开关会额外用新版覆盖游戏目录（改前留 `*.game_original`），**可能影响游戏启动**，不确定就别开。

### 游戏目录净化 / 还原

把游戏目录里的第三方注入物（loader proxy、插件数据、残留 ReShade 痕迹）**先备份再移走**，备份在 `runtime\game_backup\<时间戳>\`（含 `manifest.json` 与还原所需的文件），随时可还原。
净化前会做内容级判定：**内容不像 ReShade/loader 载荷的 DLL 不会被误移走**（例如游戏自带或他方放的正版 `d3d12.dll`）。

### Endfield Poser（摆姿 / MMD 播放，可选）

启动页第 5 个滑块就是它。装什么、怎么装都由**它自己的安装向导**决定，本程序只做三件事：

1. **下载**：从它的官方 Release 取 `Endfield-Poser-v<版本>-win64.zip`（约 6.9 MB，Release 自带 sha256 校验），解压到 `runtime\poser\`；
2. **安装**：调它包内的 `tools\deploy.ps1 -GameDir <游戏目录> -Action Install`，由向导把 `plugin\poser.dll` 与 `d3dcompiler_47.dll`（proxy）写进游戏目录，并复制 37 份角色表情校准。**本程序不直接写这两个文件** —— 向导自带校验、原子写、失败回滚与安装记录（`plugin\poser-install.json`）；
3. **开关**：关掉只把 `plugin\poser.dll` 改名为 `plugin\poser.dll.endfieldmodcontroller.disabled`（loader 只扫 `*.dll`，所以立刻不生效），**不动 proxy、不动其它插件**；要真正移除文件请用「卸载」（走向导的 Uninstall）。

游戏内：按 **L** 开面板、**P** 冻结/解冻、按住 **Alt** 取光标、`Ctrl+F5/F6/F7/F8` 播放/暂停/停止/回首帧。它还有一个独立摆姿页 `http://127.0.0.1:18923`（游戏运行时用浏览器打开；启动页有「打开摆姿页（Poser）」按钮，设置页「启动与诊断」里有「打开 Poser 日志」可直接看 `plugin\poser_log.txt`）。首次进游戏需要在游戏内确认它的《用户协议》，未确认前那个页面只给只读状态。

**它和乳摇（SecondaryMotion）能共存**，因为两者用的是同一套注入机制：游戏目录里的 `d3dcompiler_47.dll` proxy 会把 `plugin\` 下所有 `*.dll` 加载进游戏进程。因此卸载其中一方时，只要另一方还在，proxy 会被保留（上游向导与我们自己的乳摇卸载逻辑都是这么做的）。

> 上游是 **AGPL-3.0**，本程序**不随包分发**它的二进制，只从官方 Release 下载并调用它自己的安装向导；使用前请确认其协议与鹰角官方创作限制。

---

## 四、目录结构

```text
<exe 所在目录>/
├─ config.json                  运行配置（原子写；损坏会被隔离成 config.json.broken-<时间戳>）
├─ library/                     Mod 库（你拖进来的 zip 解压到这里）
└─ runtime/
   ├─ builtin/XXMI/             自动下载安装的 XXMI Launcher + Libraries + EFMI
   ├─ dlss5/                    DLSS5 底座与插件（d3d12.dll / ReShade.ini / ReShadePreset.ini
   │                            / *.addon64 / nvngx_*.dll / reshade-shaders / dlss5-feed.cfg）
   ├─ reshade/                  控制器自己的 addon 与 actions.tsv
   ├─ secondary_motion/         乳摇工具（可选）
   ├─ poser/                    Endfield Poser 安装包（从官方 Release 下载，不随包分发）
   ├─ game_backup/<时间戳>/      游戏目录净化备份（可还原）
   ├─ backups/                  引擎目录、配置等的历史备份
   ├─ logs/                     日志与诊断包（logs/bundles/*.zip 是崩溃包）
   └─ _update/                  自更新下载与残留
```

`library/` 是**你的数据**，任何自动清理都不会碰它；相反，控制器自己的产物一律带 `MC_` 前缀，便于区分。

---

## 五、常见问题

### DLSS5 相关（面板显示不正常时按顺序看）

**Q：面板显示「0 渲染」/ `NGX Hook 创建 0`？**
`nvngx_dlssnr.dll` 没就位。确认 `runtime\dlss5\` 里有这两个文件：`nvngx_dlss.dll`（58,977,904 B）与 `nvngx_dlssnr.dll`（165,840,496 B）——**游戏目录保持原版即可**，不需要动它。日志里会有 `Failed to find NVSDK_NGX_D3D12_EvaluateFeature_C` 这条（正常，它旁边的 `EvaluateFeature hooked` 才是关键）。

**Q：能进游戏，但「成功NR帧」一直是 0？**
正常情况下不该出现——初始化自检会把下面三件事都办好。真遇到了按顺序查：
1. `runtime\dlss5\dlss5-feed.log` 里是不是 `motion vectors will be zero (still images only)` —— 是的话说明运动矢量来源没配，`ReShade.ini` 的 `[GENERAL] PreprocessorDefinitions` 与 `ReShadePreset.ini` 里都要有 `DLSS5_MV_PROVIDER=1`（重跑一次「一键检测全部」会补）；
2. 日志里是不是 `Failed to compile ... DLSS5_Feed.fx: could not open included file 'ReShade.fxh'` —— 是的话说明缺 ReShade 标准头，重跑自检（`dlss5:shader_deps` 会补齐；注意 `runtime\dlss5\reshade-shaders\Textures\` 也要有文件，空目录同样不行）；
3. 日志里是不是 `LaunchPad technique found (DISABLED)`、或者只有 `LaunchPad technique found (enabled)` 却没有 `opening D3D12 session` —— 说明 preset 里的 technique 没有真正生效。先确认 `ReShadePreset.ini` 里 `Techniques=` 含 `MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx` 与 `DLSS5_Feed@DLSS5_Feed.fx`、`EffectSorting=MartysMods_LAUNCHPAD.fx,DLSS5_Feed.fx`；**必须完全退出游戏后再改**（`AutoSavePreset=1` 时 ReShade 退出会把内存状态写回、覆盖你的改动）。若仍不生效，兜底手段是进游戏按 Home → 主页 → 效果列表，把 `iMMERSE: Launchpad` 与 `DLSS5_Feed` 各点一次「置顶激活效果」（并保证 Launchpad 排在 DLSS5_Feed 之上），正常退出让 ReShade 自己写回 preset。

**Q：ReShade 提示「编译一些效果时出现了错误」？**
那是完整 shader 集合里几个无关效果（`MartysMods_FFTBLOOM.fx`、`INSIGHT.fx`、`RSRetroArch\mdapt.fx`、`DH\dh_uber_rt.fx`、`AstrayFX\RadiantGI.fx`）编译失败，**与 DLSS5 无关**，程序会把它们移到 `_quarantine_bad_shaders\`。真正要关心的是日志里有没有 `Failed to compile ... DLSS5_Feed.fx: could not open included file 'ReShade.fxh'` —— 那说明缺 ReShade 标准头，重跑一次自检即可（`dlss5:shader_deps` 会补齐）。

**Q：`dlss5-feed.addon64` 该用哪一版？**
**两版都能用，不必刻意回退。** 程序随包分发的是 0.1.0（76,800 B），而「一键安装/更新全部组件」会把它更新成上游最新版；2026-09-30 实测：**1.18.0-beta.1（332,800 B）在终末地上正常出帧**（`dlss5-feed.log` 从 13:19 到 13:22 一路到第 7200 帧、35 fps、NGX 310.8，那次游戏是正常退出）。判断它有没有工作**别只看版本号**，看两处：`runtime\dlss5\dlss5-feed.log` 里有没有 `opening D3D12 session` → `frame N delivered`，以及游戏内面板的「成功NR帧」是否在涨。（此前 README 写过"1.18 不会出帧"，2026-09-30 已按实测更正。）

### 崩溃与自检（0.6.0 起）

**Q：崩溃弹窗说「这次崩溃很可能由 Mod 资源冲突引起」，怎么办？**
自检在启动时发现你的 `Mods` 里有 Mod 覆盖了同一批资源（最常见是两个 Mod 改了同一个角色的同一批贴图/模型），它们同时生效会让游戏在**加载过程中**闪退。按弹窗里的按钮直接去「Mod 库」页，把冲突的两个里取消勾选一个 → 点「生成控制器」→ 再进游戏。这一步比先怀疑注入更容易验证。清理后还崩，再把诊断包发到 issue —— 那时弹窗会回到普通的「检测到终末地异常退出」。

**Q：自检报「随包组件与基线不一致」？**
说明 `runtime\dlss5\` 里的组件和本程序随包的那一版**文件大小不同**（多半是拿别的「DLSS5 整合包」覆盖过，或者在线组件被更新到了上游最新版）。**这只是一条差异提示，不等于有问题** —— 例如 `dlss5-feed.addon64`：随包是 0.1.0（76,800 B），而在线更新会装成 1.18.0-beta.1（332,800 B），**两版实测都能在终末地上出帧**。真觉得 DLSS5 没生效时，看 `runtime\dlss5\dlss5-feed.log` 与面板「成功NR帧」；要恢复随包版本就把 `runtime\dlss5` 改名备份 → 点「一键启动」重新展开（这一项**只提示、不自动覆盖**你的文件）。

**Q：点「一键启动」时弹出「启动前发现 Mod 冲突风险」？**
这是在**拉起 XXMI 之前**拦的一道确认，判据有两类（都是算好的事实，不是猜）：
- **资源冲突**：自检发现两个 Mod 覆盖同一批游戏资源（典型是同一角色的两个服装 Mod）；
- **崩溃记忆**：这套 Mod 组合（**或它的一部分**）以前真的崩过 —— 程序会把每次崩溃时跑的是哪套 Mod 记在 `runtime\_state\crash_memory.json`，下次勾到相同/相近组合就提醒。

点「**先去清理，不启动**」（弹窗里**右侧的橙色主选项**，默认就聚焦在它上面，直接按 Enter 也是它）会直接把你带到「Mod 库」页（取消勾选冲突项 → 「生成控制器」）；点左侧的「仍然启动」才照常继续，但游戏有可能在加载过程中闪退。清理完再启动就不会再提示。（正常退出**不会**进崩溃记忆，不会因此打扰你。）

**Q：崩溃包 / 诊断包里都有什么？**
控制器日志、终末地自己的日志（`Player.log` 与崩溃转储目录）、注入快照、Windows 事件、**DLSS5 现场**（`dlss5-feed.log` / `ReShade.ini` / `dlss5-feed.cfg`），以及 `cause.json`（这次退出的归因：Mod 冲突 / 其它崩溃 / 正常退出）。报告正文里也有一行「归因 : …」。

### 其他

**Q：乳摇管理器每次都要我选游戏文件夹？**
`<乳摇工具目录>\SecondaryMotion\settings.json` 里的 `game_data_dir` 必须是 **`<游戏目录>\SecondaryMotion`**（数据目录，不是游戏根目录）。程序初始化时会自动写好；要手动改的话注意这一点。

**Q：第一人称没效果，点面板按钮也没反应？**
`runtime\dlss5\ReShade.ini` 的 `[endfield-enhancer]` 段里，`CameraEFMICompatibility` 必须是 `1`（与 EFMI 服装 Mod 共存所必需），另外 `CameraFirstPersonMovement` / `CameraMeshHeadHiding` / `CameraFirstPersonDialogue` / `CameraSmoothPerspectiveTransition` 都建议为 `1`，`ShortcutFirstPerson=112`（F1）是切换键。程序初始化时会写入这套可用默认值。

**Q：点了一键启动，Mod 没生效 / 注入失败？**
看启动页的初始化自检结果与 `runtime\logs\launch.log`。常见原因：XXMI 配置还没生成（第一次要点两次启动）、注入库被 XXMI 自己的设置弹窗重置、`d3dx.ini` 的 `[Loader] target` 指错、或游戏目录残留了旧的 loader proxy（用"净化游戏目录"处理）。

**Q：游戏起不来 / 进游戏闪退？**
先看 `runtime\logs\bundles\` 里最新的崩溃包（程序检测到异常退出会自动打包，里面含游戏的 `Player.log`、CrashSight 日志、模块列表与我们的分析）。已排除过的常见原因：注入库同时挂了两个 ReShade 底座、mod 之间同角色冲突、游戏目录缺 `d3dcompiler_47.dll` / `vulkan-1.dll`。**也不要同时开"部署新版 nvngx"**。

**Q：第一次启动会很慢吗？**
不会。窗口 1~3 秒内出现（从零启动实测 2.7 秒），而且**任何阶段都不会出现空白窗口**：窗口底色跟随主题、加载页至少显示 0.7 秒，并分步提示「正在绑定界面 → 正在读取配置 → 正在扫描 Mod 库」。
费时间的是后台"遍历盘符找 XXMI / 3DMigoto / 乳摇工具"，它在首屏出来**之后**才开始，只影响设置页那几个「检测到的路径」字段（探测完自动补上），不影响你操作。真正看网速的是首次下载安装 XXMI / Libraries / EFMI。

**Q：下载慢 / 连不上 GitHub？**
设置页把"下载加速"设为自动、线路设为自动即可：平时单连接，慢或断流时临时并发分块并临时切镜像线路；**镜像下载物会用 Release 提供的 sha256 校验**，校验不过就丢弃重来。用完线程池即销毁，不常驻、不改 hosts、不装证书。

**Q：反作弊会不会有问题？**
本程序不注入、不碰反作弊；注入由 XXMI/EFMI 完成，且只作用于游戏目录里那几个已知文件。所有对游戏目录的改动都可备份、可还原。风险自负（见免责声明）。

**Q：崩溃了怎么反馈？**
程序检测到游戏异常退出时会自动把「控制器日志 + 游戏日志 + 崩溃转储」打包到 `runtime\logs\bundles\crash-<时间戳>.zip`，在弹窗里点「打开路径」即可定位（也可以用日志窗的「导出诊断包」）。把 zip 附到 issue 里。

---

## 六、开发

```bat
pip install -r requirements.txt
python -m pytest tests -q        :: ← 必须指定 tests 目录（见下）
python scripts/self_check.py     :: 跑测试 + 检查 dist 里的 exe / addon / --cli
python scripts/build_exe.py      :: 打包单文件 exe → dist\EndfieldModController.exe
python -m endfieldmodcontroller --cli   :: 打印状态 JSON
```

> ⚠ 不要直接在仓库根跑 `python -m pytest -q`：那会把 `_tmp\` 下的临时脚本一起收集，和 `tests\` 里的模块重名后直接报 collection error（整套要跑几分钟才中断）。**用 `python -m pytest tests -q`**（约 7 秒）。

主要模块：

| 模块 | 职责 |
| --- | --- |
| `config.py` | 配置读写（原子写/损坏隔离）、路径解析、内嵌组件探测（带缓存与"深/浅"两档） |
| `core.py` | Mod 库扫描、角色识别、ini 解析与热键接管、控制器产物生成、`d3dx_user.ini` 读写 |
| `activation.py` | 选择解析（同角色互斥/依赖按需）、staging 生成与清理 |
| `launcher.py` | 一键启动、注入库维护、XXMI 配置读写、ReShade 运行时准备、进程收尾 |
| `api.py` | 暴露给前端的接口层（pywebview `js_api`）；构造必须保持"快"，重活放后台预热 |
| `initialize.py` | 初始化自检（ReShade.ini 重建并**保留所有段**、DLSS5 shader/preset/运动矢量、游戏目录运行库、Mod 冲突检测） |
| `secondary_motion.py` | 乳摇：状态、注入、模板实例化、`settings.json`（游戏数据目录） |
| `poser.py` | Endfield Poser（摆姿 / MMD）：状态、安装包下载、调**它自己的**安装向导、开关（重命名 dll）、只读读它的摆姿页 |
| `dependencies.py` / `runtime_deps.py` | 依赖清单、下载与解压（逐文件原子替换）、XXMI/Libs/EFMI 安装 |
| `dlss5_fetcher.py` / `reshade_integration.py` | DLSS5 组件、ReShade 集成与游戏目录注入审计 |
| `game_clean.py` | 游戏目录净化/还原（备份式、内容级判定、越界拒绝） |
| `fastnet.py` / `github.py` / `fsutil.py` | 下载（并发/镜像/校验）、GitHub 查询与缓存、哈希与原子写公共件 |
| `diagnostics.py` / `crashwatch.py` | 日志、诊断包、崩溃监视与报告 |
| `web/` | 前端（原生 HTML/CSS/JS，pywebview 里跑） |

### 测试清单

仓库根目录的 `TESTING.md` 是一份可照做的全功能验收清单（按测试环境分段、编号稳定，出问题按编号反馈即可）。

---

## 七、发布规则

三个固化脚本（**构建**与**上传**分开；上传永远由你自己执行）：

```bat
python scripts\build_release.py          :: 静态检查 → 构建最新版 + 带版本号副本 + 伪旧版 → 归置旧版
python scripts\prepare_release.py        :: 校验产物 + 生成 assets-bundle.zip + 打印上传指引
python scripts\upload_release_assets.py  :: 上传两个附件（大文件走直连，见下）
```

> **大文件上传的坑（实测）**：机器上开着 Steam++ / Watt Toolkit 时，它会把 github
> 相关域名写进 hosts 指向 `127.0.0.1` 的本地反代，而该反代对**大 body 的 POST 上传**支持不好 ——
> 实测 1 / 5 / 20 / 60 MB 都能过，126 MB 的 `assets-bundle.zip` 会在发出约 100 KB 后被强断
> （`gh release upload` 报 HTTP 502：`RequestBodyDestination … 远程主机强迫关闭了一个现有的连接`）。
> `upload_release_assets.py` 的做法是：用 DoH 查真实 IP，再用 `curl --resolve` 直连上传
> （实测 126 MB / 23 秒 / 5.7 MB/s 成功），**不改 hosts、不动系统代理**，下载路径不受影响。

`build_release.py` 的静态检查（任一失败即中止，**不会**产出半成品）：所有模块 `py_compile`、
`node --check web/app.js`、`python -m pytest tests -q`。

本地产出**三份 exe**，旧版自动归置：

| 产物 | 用途 | 是否上传 |
| --- | --- | --- |
| `dist\EndfieldModController.exe` | 最新版，唯一发行的 exe | ✅ 上传 |
| `dist\EndfieldModController-<版本>.exe` | 带版本号副本（留档） | ❌ 不上传 |
| `EndfieldModController-0.1.9-from-<版本>.exe`（`dist\` 与仓库根各一份） | 伪旧版，用于测试自更新 | ❌ 不上传 |
| `dist\_old\` | 上一代及更早的带版本号副本（构建时**自动归置**；旧伪旧版直接删除） | — |

- 「只上传不带版本号的那个」这条规则**只约束 exe**；其它附件照常上传。
- `dist\` **只留构建产物**：构建脚本会自动清掉 exe 在 dist 里跑过留下的 `config.json` / `runtime\` /
  `library\`，以及早期 `--onedir` 的残留目录（`dist\EndfieldModController\`）。
- Release 附件 = **`EndfieldModController.exe` + `assets-bundle.zip`** 两个。
  单文件 exe 装不下运行时资产（`assets/nvngx` 本身是 xz 分卷），程序在本地找不到
  `assets\` 时会自动从 Release 下载这个包并展开 —— `prepare_release.py` 会调用
  `scripts\build_assets_bundle.py` 现打一份 `dist\assets-bundle.zip`（+ `.sha256`）。
  ⚠️ **改过 `assets\` 之后一定要重新生成它**，别拿旧包发布。
- **不做便携版**（没有 portable zip，也没有相应的打包脚本）。
- 版本号：与 GitHub 上的有区别就升下一版，未推送期间只领先一个。
- 伪旧版的版本号固定写成 `0.1.9`（代码是最新的），命名刻意取"旧版本号"以便一眼分辨；
  上一代伪旧版在下次构建时**自动删除**。

---

## 八、第三方组件与许可

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| [XXMI Launcher](https://github.com/SpectrumQT/XXMI-Launcher) | 注入器与启动器 | MIT |
| [XXMI-Libs-Package](https://github.com/SpectrumQT/XXMI-Libs-Package) / [EFMI-Package](https://github.com/SpectrumQT/EFMI-Package) | 注入库与服装 Mod 引擎 | MIT |
| [3DMigoto](https://github.com/bo3b/3Dmigoto) | EFMI 的底座 | MIT |
| [ReShade](https://reshade.me/) | 后处理底座（Addon 版） | BSD-3 |
| [RenoDX DLSS](https://github.com/clshortfuse/renodx) | DLSS5 神经渲染 | MIT |
| Endfield Enhancer（RenoDX 出品） | 第一人称 / 相机（英文原版） | MIT |
| **第一人称中文补丁** —— B站 up 主 **Hirahido** | 第一人称 / 相机面板的**中文**版本 | 版权归原作者 |
| [iMMERSE](https://github.com/martymcmodding/iMMERSE)（Marty's Mods） | ReShade 后处理链（Launchpad 等） | MIT |
| DLSS 5 Feed（`dlss5-feed.addon64`） | 给 DLSS5 喂颜色/运动矢量/深度 | 见其说明（无公开仓库，随包分发） |
| [ShakingBreastManager / SecondaryMotion](https://github.com/Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics) | 乳摇 | 见上游仓库 |
| [Endfield Poser](https://github.com/OedoSoldier/Endfield-Poser)（`honxi1/Endfield-Poser` 的功能分支） | 摆姿 / MMD 播放（可选） | **AGPL-3.0** —— **不随包分发**，只从它的官方 Release 下载并调用它自己的安装向导 |
| **Endfield PS-T DrawSection Fix v2.1**（《终末地Mod修复工具包》v1.5）—— **B站 up 主 可可HXL** | Mod 卡片的「修复（实验性）」与「一键修复所有」 | 版权归原作者（B站搜索「可可HXL」可找到工具包与教程）；**随包分发**，使用方式按其教程：在**临时目录**里跑，不把 `_ps_t_draw_fix_backup_*` 与日志留在 Mods 里 |
| NVIDIA NGX 运行库（`nvngx_dlss.dll` / `nvngx_dlssnr.dll`） | DLSS 与神经渲染运行库 | NVIDIA 版权，随包仅为免去手动下载 |

**关于第一人称中文补丁（特别声明）**：随包分发的第一人称**中文**补丁由 **B站 up 主 Hirahido** 制作，
版权归其所有（源自作者发布的"终末地EE"）。
本程序**只做分发与安装编排**，不修改其内容；如果你是该补丁的作者且不希望被随包分发，
请在 issue 里说明，我会立即移除。英文原版第一人称插件来自 **Endfield Enhancer**（RenoDX 出品，无公开仓库，同样随包分发）。

各组件版权归原作者所有。本程序只做编排、自检与备份还原，不修改这些组件的源码。

---

## 九、免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**；请自行确认你所在环境的规则。
- 本程序会读写游戏目录中的注入类文件（`d3d12.dll` / `d3dcompiler_47.dll` / `vulkan-1.dll` / `plugin\sbm.dll` / `plugin\poser.dll` / `plugin\poses\` / `plugin\mmd\` / `SecondaryMotion\` 等），但一律先备份、且提供一键还原；**不会**修改游戏本体、资源与存档。
- 第三方组件由其原作者维护，出问题请先到对应仓库反馈；本程序的集成问题欢迎开 issue。
