# EndfieldModController

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）** 以及 **乳摇（SecondaryMotion）** 统一到一次「一键启动」里，并自动维护各项注入与初始化自检。

Windows 桌面程序（Python + PyWebview），单文件 exe，**零配置启动即用**。当前版本 **0.3.1**。

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
| **游戏目录净化 / 还原** | 把第三方注入物**先备份再移走**（`runtime/game_backup/…`），随时一键还原；被移走的系统模块会自动从 System32 补回 |
| **诊断与日志** | 启动日志、崩溃监视、一键导出诊断 zip（含日志、注入状态、Windows 事件） |
| **更新** | 检查/下载新版并自更新（下载后校验 sha256，退出后由脚本替换并重启）；组件（XXMI / EFMI / 乳摇）也能单独更新 |
| **下载兜底** | 内置轻量加速：慢/抖时临时并发分块，直连不通时临时换镜像线路 —— 按需启用、用完即放，不装证书、不改系统 |

### 注入链（同一进程内同时生效）

```text
唯一的 ReShade 底座  runtime\dlss5\d3d12.dll（ReShade 6.8.0 Addon 版）
  ├─ renodx-dlss5-4.7_汉化.addon64      → DLSS5 神经渲染
  ├─ renodx-endfield-enhancer.addon64   → 第一人称 / 相机
  ├─ dlss5-feed.addon64                 → DLSS5 输入（需启用 DLSS5_Feed technique）
  ├─ trans-zh.addon64                   → 面板汉化
  └─ reshade-shaders\                   → 含 DLSS5_Feed.fx
服装 Mod 引擎  EFMI\d3d11.dll
```

XXMI Launcher 启动游戏时按「注入库」注入上表里的 DLL，注入库由本程序维护，启动页的开关就是它的快捷切换。
**一个游戏进程只能有一个 ReShade 底座**，所以不要把两个 `d3d12.dll` 同时注入。

---

## 二、运行与安装

### 方式 A：直接双击 exe（推荐）

1. 下载 `EndfieldModController.exe`（Release 里只有这一个文件）；
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
3. XXMI 的配置是**它首次运行时自己生成**的，所以本程序会先拉起一次 XXMI 生成配置、随后关闭它，并提示：

   > 第一次启动：已临时拉起 XXMI 生成它的配置文件，随后已关闭。**请再点一次「一键启动」**。

4. 再点一次「一键启动」就会真正写好注入库并拉起 XXMI。

> **DLSS5 那套组件没有上游可下载**（`renodx-endfield-enhancer.addon64`、`trans-zh.addon64`、`nvngx_dlssnr.dll` 全网都没有自动可用的发布源），需要随包自备或从可用的旧环境复制到 `runtime\dlss5\`。缺了会明确提示缺哪个文件，而不是静默失败。

---

## 三、日常使用

### Mod 库页

- **导入**：把 `.zip` 拖进窗口 → 出现全屏提示框 → 松手即导入（仅"Mod 库"页接受拖放；拖出窗口或按 Esc 会取消提示）。
- **角色识别**：导入后按 Mod 名/ini 里的线索猜角色；不确定会弹窗让你选，也可以稍后点卡片上的"角色待确认"。
- **勾选**：勾选即保存（同角色自动互斥）。点「生成控制器」把选择落成 EFMI 要加载的内容。
- **热键**：Mod 自带的热键会被统一接管（改成 `VK_F24`），改由本程序的面板/动作队列驱动 —— 避免 Mod 自己的按键和游戏冲突。

### 启动页

- **一键启动**：补齐组件 → 同步 XXMI 注入库 → 初始化自检 → 拉起 XXMI（不自动进游戏；进游戏由 XXMI 或「启动游戏」按钮完成）。
- **打开官方 XXMI**：只打开 XXMI 自己的界面，不动注入库。
- **强制关闭**：收掉残留的 loader / 游戏进程（**不会**在你没要求的情况下强杀正在玩的游戏）。

### 设置页

路径配置（XXMI / 游戏 / loader / 乳摇工具）、下载加速与线路、主题、单实例与游戏多开防护、是否部署新版 nvngx、依赖清单等。
`config.json` 里的键与默认值可参考 `config.example.json`（由程序默认值直接导出）。

### 游戏目录净化 / 还原

把游戏目录里的第三方注入物（loader proxy、插件数据、残留 ReShade 痕迹）**先备份再移走**，备份在 `runtime\game_backup\<时间戳>\`（含 `manifest.json` 与还原所需的文件），随时可还原。
净化前会做内容级判定：**内容不像 ReShade/loader 载荷的 DLL 不会被误移走**（例如游戏自带或他方放的正版 `d3d12.dll`）。

---

## 四、目录结构

```text
<exe 所在目录>/
├─ config.json                  运行配置（原子写；损坏会被隔离成 config.json.broken-<时间戳>）
├─ library/                     Mod 库（你拖进来的 zip 解压到这里）
└─ runtime/
   ├─ builtin/XXMI/             自动下载安装的 XXMI Launcher + Libraries + EFMI
   ├─ dlss5/                    DLSS5 底座与插件（d3d12.dll / ReShade.ini / *.addon64 / reshade-shaders）
   ├─ reshade/                  控制器自己的 addon 与 actions.tsv
   ├─ secondary_motion/         乳摇工具（可选）
   ├─ game_backup/<时间戳>/      游戏目录净化备份（可还原）
   ├─ backups/                  引擎目录、配置等的历史备份
   ├─ logs/                     日志与诊断包（logs/bundles/*.zip）
   └─ _update/                  自更新下载与残留
```

`library/` 是**你的数据**，任何自动清理都不会碰它；相反，控制器自己的产物一律带 `MC_` 前缀，便于区分。

---

## 五、常见问题

**Q：点了一键启动，Mod 没生效 / 注入失败？**
看启动页的初始化自检结果与 `runtime\logs\launch.log`。常见原因：XXMI 配置还没生成（第一次要点两次启动）、注入库被 XXMI 自己的设置弹窗重置、`d3dx.ini` 的 `[Loader] target` 指错、或游戏目录残留了旧的 loader proxy（用"净化游戏目录"处理）。

**Q：游戏起不来 / 进游戏闪退？**
先看 `runtime\logs\` 里的崩溃信息与诊断 zip。常见原因：游戏目录缺 `d3dcompiler_47.dll` / `vulkan-1.dll`（净化时会自动补回，补不回会明确报错）、注入库同时挂了两个 ReShade 底座、或 mod 之间同角色冲突。

**Q：第一次启动会很慢吗？**
不会。窗口 1~3 秒内出现（从零启动实测 2.7 秒），而且**任何阶段都不会出现空白窗口**：窗口底色跟随主题、加载页至少显示 0.7 秒，并分步提示「正在绑定界面 → 正在读取配置 → 正在扫描 Mod 库」。
费时间的是后台"遍历盘符找 XXMI / 3DMigoto / 乳摇工具"，它在首屏出来**之后**才开始，只影响设置页那几个「检测到的路径」字段（探测完自动补上），不影响你操作。真正看网速的是首次下载安装 XXMI / Libraries / EFMI。

**Q：下载慢 / 连不上 GitHub？**
设置页把"下载加速"设为自动、线路设为自动即可：平时单连接，慢或断流时临时并发分块并临时切镜像线路；**镜像下载物会用 Release 提供的 sha256 校验**，校验不过就丢弃重来。用完线程池即销毁，不常驻、不改 hosts、不装证书。

**Q：反作弊会不会有问题？**
本程序不注入、不碰反作弊；注入由 XXMI/EFMI 完成，且只作用于游戏目录里那几个已知文件。所有对游戏目录的改动都可备份、可还原。风险自负（见免责声明）。

**Q：崩溃了怎么反馈？**
在日志窗点「导出诊断包」，把生成的 zip 附到 issue 里（含日志、注入状态、Windows 应用错误事件）。附崩溃 dump 更好。

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
| `dependencies.py` / `runtime_deps.py` | 依赖清单、下载与解压（逐文件原子替换）、XXMI/Libs/EFMI 安装 |
| `dlss5_fetcher.py` / `reshade_integration.py` | DLSS5 组件、ReShade 集成与游戏目录注入审计 |
| `game_clean.py` | 游戏目录净化/还原（备份式、内容级判定、越界拒绝） |
| `fastnet.py` / `github.py` / `fsutil.py` | 下载（并发/镜像/校验）、GitHub 查询与缓存、哈希与原子写公共件 |
| `diagnostics.py` / `crashwatch.py` | 日志、诊断包、崩溃监视与报告 |
| `web/` | 前端（原生 HTML/CSS/JS，pywebview 里跑） |

---

## 七、发布规则

三个固化脚本（**构建**与**上传**分开；上传永远由你自己执行）：

```bat
python scripts\build_release.py          :: 静态检查 → 构建最新版 + 带版本号副本 + 伪旧版 → 归置旧版
python scripts\prepare_release.py        :: 校验产物 + 生成 assets-bundle.zip + 打印上传指引
python scripts\upload_release_assets.py  :: 上传两个附件（大文件走直连，见下）
```

> **大文件上传的坑（2026-10-01 实测）**：机器上开着 Steam++ / Watt Toolkit 时，它会把 github
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
  单文件 exe 装不下约 125 MB 的运行时资产（`assets/nvngx` 本身是 xz 分卷），程序在本地找不到
  `assets\` 时会自动从 Release 下载这个包并展开 —— `prepare_release.py` 会调用
  `scripts\build_assets_bundle.py` 现打一份 `dist\assets-bundle.zip`（+ `.sha256`）。
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
| [Endfield Enhancer](https://github.com/RenoDX-Suite/) | 第一人称 / 相机 | MIT |
| [iMMERSE](https://github.com/MartysMods/iMMERSE) | ReShade 后处理链 | MIT |
| ShakingBreastManager / SecondaryMotion | 乳摇 | 见上游仓库 |

各组件版权归原作者所有。本程序只做编排、自检与备份还原，不修改这些组件的源码。

---

## 九、免责声明

- 本程序**不是**官方工具，与鹰角网络 / Hypergryph 无关。
- 使用 Mod 可能违反游戏用户协议，**风险由使用者自负**；请自行确认你所在环境的规则。
- 本程序会读写游戏目录中的注入类文件（`d3d12.dll` / `ReShade.ini` / `actions.tsv` 等），但一律先备份、且提供一键还原；**不会**修改游戏本体、资源与存档。
- 第三方组件由其原作者维护，出问题请先到对应仓库反馈；本程序的集成问题欢迎开 issue。
