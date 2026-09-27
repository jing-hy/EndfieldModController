# EndfieldModController

《明日方舟：终末地》的一站式 Mod 管理器：把 **DLSS5 神经渲染 + 第一人称视角 + 服装 Mod（EFMI）** 以及 **ShakingBreastManager** 统一到一次「一键启动」里，并自动维护各项注入与初始化自检。Windows 桌面程序（Python + PyWebview），开箱即可双击 exe 运行。

> 本程序**只做编排与自检**，不实现注入、不改游戏本体文件。注入由 XXMI Launcher 完成，服装 Mod 由 EFMI 加载，神经渲染与第一人称是挂在同一个 ReShade 底座下的 addon。

---

## 一、它能做到什么

本机实测通过的组合（同一进程内同时生效）：

```text
唯一的 ReShade 底座  runtime\dlss5\d3d12.dll（ReShade 6.8.0）
  ├─ renodx-dlss5-4.7_汉化.addon64      → DLSS5 神经渲染
  ├─ renodx-endfield-enhancer.addon64   → 第一人称 / 相机
  ├─ dlss5-feed.addon64                 → DLSS5 输入（需启用 DLSS5_Feed technique）
  ├─ trans-zh.addon64                   → 面板汉化
  └─ reshade-shaders\                   → 含 DLSS5_Feed.fx
服装 Mod 引擎  EFMI\d3d11.dll
```

XXMI Launcher 启动游戏时注入上表中的 DLL，「注入库」由本程序自动维护；启动页的开关就是它的快捷切换。**一个游戏进程只能有一个 ReShade 底座**，所以不要把两个 `d3d12.dll` 同时注入。

### 内置集成的组件

| 组件 | 说明 |
| --- | --- |
| **DLSS5 神经渲染** | 通过 RenoDX DLSS addon 提供 |
| **第一人称视角** | 通过 Endfield Enhancer addon 提供（相机与头部隐藏） |
| **服装 Mod（EFMI）** | 服装/外观 Mod 引擎，支持同角色互斥、快捷键屏蔽 |
| **ShakingBreastManager** <br><sub>次级运动 / 身体物理插件（v2.3.5）</sub> | 保持它自己的原生 Manager 界面独立运行；本程序负责状态显示、一键拉起它自己的 exe、补齐或卸载它的注入、以及从原仓库检查更新 |

---

## 二、重要前提：第三方组件请放在**浅路径**

这是实测踩出来的硬限制，**不遵守会表现为「游戏闪退」或「Mod 完全不生效」**：

> EFMI / ReShade 按**自身所在目录**解析 `d3dx.ini`、addon 与 shader 路径。路径一长，游戏就会崩或插件静默失效。

| 放这里 | 结果 |
| --- | --- |
| `D:\XXMI2`（8 字符） | 可用 |
| `runtime\builtin\XXMI`（50 字符） | **不可用** |
| `D:\DLSS5`（8 字符） | 可用 |
| `runtime\dlss5`（38 字符） | **不可用** |

用**目录联接（junction）也不管用** —— 进程看到的仍是长路径。

所以推荐的部署形态是把第三方组件放在盘符根下的短目录（如 `D:\XXMI2`、`D:\DLSS5`），控制器本身可以放任意位置。

---

## 三、本仓库**不包含**什么

为避免误传个人数据与超限文件，仓库里**没有**：

- `library/` —— 你自备的服装 Mod（体积大且各有作者授权）
- `runtime/` —— 第三方组件、日志、崩溃包、备份（体积可达数十 GB）
- `config.json` —— 你的本机路径配置（仓库里给的是 `config.example.json`）
- `_tmp/`、`dist/` —— 临时产物与构建输出
- NVIDIA 运行库（`nvngx_dlss*.dll`，百余 MB）—— 请从游戏目录或 NVIDIA 官方获取，**不随本仓库分发**

第三方组件请按第九节各原仓库自行下载，或使用 Release 里的 exe。

---

## 四、快速开始

### 方式 A：直接双击 exe（推荐）

1. 从 Release 下载 `EndfieldModController.exe`（单文件，**不需要装 Python**）；
2. **把它放进你的工作区目录**（例如已有 `library\` 和 `runtime\` 的那个目录）；
3. **双击它**即可，全程不会出现命令行黑窗；
4. 在界面里点「一键启动」—— 它会先跑初始化自检，缺什么补什么，然后拉起 XXMI Launcher。

> **exe 旁边的目录就是「用户数据根」**：`config.json`、`runtime\`（日志与崩溃包）、
> `library\`（你的 Mod 库）都会留在那里。也就是说 **exe 放哪儿，它的 Mod 库就在哪儿** ——
> 想让 exe 用上已有的 Mod 库，把它复制到原工作区目录再双击；放到一个空文件夹里，
> 界面里自然一个 Mod 都不会有。把 exe 连同这些目录一起搬走即可整体迁移。

想自己从源码打包成 exe：

```bash
python scripts/build_exe.py            # 单文件 dist/EndfieldModController.exe
python scripts/build_exe.py --onedir   # 目录模式：启动更快，但不是单文件
python scripts/build_exe.py --console  # 保留控制台，调试 --cli 用
```

### 方式 B：从源码运行

```bash
pip install -r requirements.txt
python -m endfieldmodcontroller          # 打开 Pywebview UI
python -m endfieldmodcontroller --cli    # 只看状态
python -m endfieldmodcontroller.cli state
```

Windows 下也可以直接 `run.bat` / `run.vbs`。

### 首次配置

打开设置页，填写：

- Mod 库目录（默认 `library`）
- staging Mods 目录（你的 EFMI `Mods` 目录）
- XXMI Launcher 路径（**浅路径**）
- `Endfield.exe` 路径
- DLSS5 底座目录（含 `d3d12.dll` 与各 addon）
- ShakingBreastManager 工具目录

**配置文件删掉也能启动** —— 默认值全部是相对路径，缺失字段会按内嵌组件自动补齐。

---

## 五、启动时会自动做什么

点「一键启动」会依次执行初始化自检（`initialize.ensure_all`），当前共 **14 项**：

| 检查 | 内容 |
| --- | --- |
| `dlss5_dir` | 底座必需的 `d3d12.dll`、各 addon、plugin、shader 是否在位，缺则从素材目录/备份/内置副本补齐 |
| `reshade_ini` | `ReShade.ini` 是否含 `[endfield-enhancer]` 段、路径是否指向当前目录，缺则用模板重建（旧文件留 `.bak`） |
| **`dlss5_preset`** | `PresetPath` 指向的 preset 是否存在**且启用了 `DLSS5_Feed`** —— 缺了它 DLSS5 **静默不工作**（见第六节） |
| `game_libs` | 游戏目录 `nvngx_dlss.dll` 等运行库，**只在缺失时补齐，绝不覆盖你已有的文件** |
| `mod_conflicts` | EFMI `Mods` 目录里是否有**同角色两个 Mod**（会直接导致游戏崩溃） |
| `controller` / `staging` | 控制器 ini 与 Mod staging 是否与当前勾选一致 |
| `sbm` | **ShakingBreastManager** 的注入是否完整（两个 proxy + `plugin\sbm.dll`） |

其余项目（注入库两条路径、ReShade 段、游戏运行库等）同样逐项校验；补不了的会标成「待处理」并 WARN，**不会静默启动**。

### 手动放进 Mods 的 Mod 会被自动收编

如果你习惯直接把 Mod 文件夹丢进 EFMI 的 `Mods` 目录，本程序在每次启动时会先做一次同步：

1. 找出 `Mods` 里**不是控制器生成**的那些目录（控制器自己的产物一律带 `MC_` 前缀）；
2. 与 Mod 库比对 —— **先按目录名，再按 ini 里的 `namespace` 特征**（所以你把文件夹改过名也认得出来）；
3. **库里已有** → 直接在界面上勾选为启用；
4. **库里没有** → 复制进 `library\`，再勾选为启用；
5. 收编后把手动目录从 `Mods` 移除，避免和随后生成的 staging 副本构成「同角色成对」。

### Mod 的角色会自动识别，拿不准就问你

每个 Mod 会被自动归类到所属角色（同角色互斥的依据）。识别结果分三种：

- **高置信** —— 名称开头就匹配到角色（中文名、官网英文代号都认，如 `埃特拉变肥美` 或 `estella_bikini`），直接用；
- **不确定** —— 一个都没匹配到，或者同时出现多个角色名分不清主次；
- **不确定时会弹窗让你选**，每行会写明原因（「名字里没找到任何角色名」/「出现了多个角色名，分不清哪个才是主体」），候选里把匹配到的排在前面。

选完会写进该 Mod 自己的 `mod.meta.json`，**以后不再问你**，而且跟着 Mod 目录走 —— 迁移、重扫都不会丢。

角色表在 `endfieldmodcontroller/characters.json`，抓自[官网干员情报页](https://endfield.hypergryph.com/operator)（33 位干员），含各种译名变体（佩丽卡/佩利卡、赛希/塞希/塞西、艾维文娜/艾闻维娜、弭弗/弥弗、昼雪/小羊等）。

---

## 六、关于 DLSS5 不生效（请先看这条）

如果面板上出现 `NGX Hook: 创建0` / `成功NR帧: 0` / `0xBAD00007`，**多半不是插件坏了、也不是显卡不支持**，而是 ReShade 里没有任何 technique 被启用。

DLSS5 addon 只在 `DLSS5_Feed` technique 执行**之后**才会去调 DLSS/NGX；而 `DLSS5_Feed.fx` 还要求 `MartysMods_Launchpad` 启用**且排在它上方**。preset 文件由 `ReShade.ini` 里的 `PresetPath` 指定（本程序默认写好）：

```ini
Techniques=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
TechniqueSorting=MartysMods_Launchpad@MartysMods_LAUNCHPAD.fx,DLSS5_Feed@DLSS5_Feed.fx
```

注意 `AutoSavePreset=1` 时，**游戏运行中改 preset 会被 ReShade 在退出时覆盖** —— 改动前请先完全退出游戏。

---

## 七、崩溃了怎么反馈

一键启动后程序会在后台跟踪 `Endfield.exe`，退出时自动收集现场并打包：

- 日志目录：`runtime\logs\`
- 崩溃包：`runtime\logs\bundles\crash-<时间戳>.zip`（含控制器日志、游戏 `Player.log`、CrashSight 记录、官方转储、注入快照）

**把 zip 直接发到 issue 即可**，里面已经包含定位所需的一切。

关于「崩溃判定」的说明，避免误报困惑：程序用的是 CrashSight 的 **`uploadCrash`**（上传崩溃转储）作为判据。`reportException` **不算** —— 游戏自己会反复记录一些被捕获、并不致命的异常（例如 `[ItemBag]` scope 回退失败），拿它当信号会导致每次正常退出都弹「异常退出」。

---

## 八、目录结构

```text
endfieldmodcontroller/          # Python 包
├─ config.py         # 配置（默认值均为相对路径 + autofill 自愈 + 打包后数据根处理）
├─ characters.json   # 33 位干员的角色名对照表
├─ core.py           # Mod 扫描 / 角色识别 / INI 解析 / 控制器生成
├─ activation.py     # 同角色互斥、依赖按需解析、staging、手动 Mod 收编
├─ launcher.py       # 启动编排、注入库维护、addon 启停
├─ initialize.py     # 启动前 14 项自检与补齐
├─ secondary_motion.py  # ShakingBreastManager 集成
├─ crashwatch.py     # 崩溃取证与崩溃包
├─ api.py            # Pywebview 后端 API
└─ app.py            # 入口
web/                # 前端 HTML/CSS/JS
scripts/            # build_exe.py / package_release.py / self_check.py 等
docs/               # 开发与排障文档
tests/              # 单元测试
```

---

## 九、第三方组件（均为 MIT 许可）

下列组件**均为 MIT 许可**，出处如下。本仓库**不包含**它们，请从各自原仓库获取，或使用 Release 里的 exe：

| 组件 | 用途 | 原仓库 |
| --- | --- | --- |
| XXMI Launcher | 启动游戏并注入 DLL 的加载器 | [SpectrumQT/XXMI-Launcher](https://github.com/SpectrumQT/XXMI-Launcher) |
| EFMI | 终末地服装 Mod 引擎（3DMigoto 系） | 随 XXMI Launcher 分发（[SpectrumQT](https://github.com/SpectrumQT)） |
| ReShade | 唯一的图形底座 `d3d12.dll` | [crosire/reshade](https://github.com/crosire/reshade) |
| RenoDX DLSS addon | DLSS / 神经渲染 | [yumlevi/renodx-dlss-installer](https://github.com/yumlevi/renodx-dlss-installer)（RenoDX 本体：[clshortfuse/renodx](https://github.com/clshortfuse/renodx)） |
| DLSS5-Feeder | `dlss5-feed.addon64` 与 `DLSS5_Feed.fx` | [jlrouzies-fr/DLSS5-Feeder](https://github.com/jlrouzies-fr/DLSS5-Feeder) |
| iMMERSE / MartysMods | `MartysMods_LAUNCHPAD` 等效果 | [clayne/iMMERSE](https://github.com/clayne/iMMERSE) / [martymcmodding](https://github.com/martymcmodding/martymcmodding) |
| DLSS5 素材整合 | 底座与 addon 的打包来源 | [faisalkindi/DLSS5oneclick](https://github.com/faisalkindi/DLSS5oneclick) |
| **ShakingBreastManager** | **次级运动 / 身体物理插件（乳摇）** | [Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics](https://github.com/Sp1cHless/Arknights-Endfield-Plugin-Secondary-bodyphysics) |
| 3DMigoto | EFMI 所基于的框架 | [bo3b/3Dmigoto](https://github.com/bo3b/3Dmigoto) |

NVIDIA 运行库（`nvngx_dlss.dll` / `nvngx_dlssnr.dll`）**不随本仓库或便携包分发**，请从游戏目录或 NVIDIA 官方渠道获取。

本项目的路线参考了 B 站教程 `BV1XMh76UEA5`《以防你不知道，你也可以终末地+XXMI+DLSS5+第一人称视角》，感谢原作者的探索。

---

## 十、测试

```bash
python -m pytest tests -q          # 单元测试
python scripts/self_check.py       # 测试 + 构建产物检查
```

---

## 十一、免责声明

- 使用 Mod 与第三方注入**可能违反游戏 ToS**，存在账号风险，请自行判断。
- 本程序**默认不写游戏目录**：仅在你确认的注入路径上操作，所有覆盖都会留下可回滚备份。
- 第三方组件的可用性、兼容性与授权由各自作者决定，与本项目无关。
