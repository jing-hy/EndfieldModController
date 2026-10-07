# 调研报告：Endfield + EFMI/3DMigoto 注入后 45 秒 nvgpucomp64.dll 崩溃

调研人：Anvil（技术调研员 subagent）　调研日期：2026-09-27
目标：找出 `nvgpucomp64.dll` 0xc0000005（driver 32.0.16.1692 / RTX 5080 / driver 616.92）与 3DMigoto/EFMI 注入的已知关联、社区已知做法与推荐配置。

---

## 0. 本机实证（先于网上资料，权重最高）

| 事实 | 证据来源 |
|---|---|
| 出错模块版本 `32.0.16.1692`（timestamp 0x6a9b31ec），驱动 616.92，RTX 5080，vbios 98.03.3b.c0.68 | `nvidia-smi`；`C:\Windows\System32\DriverStore\FileRepository\nv_dispi.inf_amd64_b20cc8aeaed64fc2\nvgpucomp64.dll` |
| 事件日志 6 次崩溃，偏移分成两组：`0x3c50b6b`（12:26、11:49、11:44）与 `0x3177615`（11:29、11:28、11:23、11:21） | Application 日志 Application Error |
| **9/26 还有 6 次 `nvoglv64.dll`（NVIDIA OpenGL 驱动）0xc0000005 崩溃**（17:43–18:32），以及 1 次 EndfieldBase.dll、1 次 ucrtbase 0x40000015 | Application 日志 |
| 显卡列表里有 **2 个虚拟显示器适配器**：`OrayIddDriver Device`（向日葵远控）、`MuMu Virtual Display Adapter`（MuMu 模拟器），以及 **AMD Radeon(TM) Graphics 核显**（CPU 是 Ryzen 7 9800X3D，主板 ASUS TUF B650EM-PLUS WIFI，BIOS 3265） | `Win32_VideoController` |
| 无任何 WHEA-Logger / Kernel-Power 41 / BugCheck / 蓝屏；无 minidump | System 日志、`C:\Windows\Minidump` |
| 当前 d3dx.ini：`load_library_redirect = 2`、`allow_create_device = 1`、`skip_early_includes_load = 0`、`config_initialization_delay = -1`、`dll_initialization_delay = 0`、`calls = 1`、`track_region_hashes = 1`、`allow_buffer_resize = 0` | `runtime\migoto\d3dx.ini` |
| 游戏目录里同时存在多套注入物：`ReShade.log`（ReShade 6.8.0）、`终末地EE.addon64`、`renodx-dlss.addon64.(disabled)`、`endfieldmodcontroller.addon64`、`nvngx_dlssnr.dll`（165 MB，9/26 12:23 写入） | 游戏根目录 |
| 9/26 的一次运行中 **ReShade 是以 `D3D12.dll` 注入 `PlatformProcess.exe`** 的（不是 d3d11.dll） | `ReShade.log1` |
| 运行版本：XXMI Launcher 2.2.1 / XXMI DLL 1.1.7 / EFMI 1.4.7 | `XXMI Launcher Log.txt` |

> 关键推论：本机崩溃**不止发生在注入后的 DX11 路径**（还有 OpenGL 驱动路径、以及 ReShade-as-D3D12 路径），但全部落在 NVIDIA 驱动的着色器编译/后端模块上。这与"3DMigoto 注入 → 驱动编译 mod 替换后的 DXBC 时炸掉"一致，也说明**驱动侧因素占相当比重**。

---

## 1. nvgpucomp64.dll 崩溃与 3DMigoto / D3D11 hook 的已知关联

| # | 来源 | 结论 / 做法 | 可信度 |
|---|---|---|---|
| 1.1 | [NVIDIA Dev Forum: RTX 5070 Ti nvgpucomp64.dll exception…](https://forums.developer.nvidia.com/t/rtx-5070-ti-nvgpucomp64-dll-exception-thrown-when-shader-uses-gl-nv-shader-sm-builtins/343335) | **最强同源证据**。同一驱动 `32.0.16.1692` 下，另一用户在 Black Myth Wukong（UE5，D3D12）**启动后 35–55 秒 100% 复现** nvgpucomp64 崩溃，报 2 种异常码 `0xc0000005` 与 `0x80000003`。他明确排除：着色器缓存损坏、后台程序干扰、DLSS/帧生成全关、HAGS 开关。→ 该驱动版本的 nvgpucomp64 在同为民用 50 系的机器上可被"启动后一分钟内的着色器/PSO 编译"稳定触发。 | 高（未官方确认，但版本号+时间窗完全吻合） |
| 1.2 | [Dota2-Gameplay #34220](https://github.com/ValveSoftware/Dota2-Gameplay/issues/34220) | RTX 5070，`INVALID_POINTER_READ_c0000005_nvgpucomp64.dll!Unknown`，栈为 `rendersystemdx11 → d3d11!CDevice::CreatePixelShader/VertexShader → nvwgf2umx → nvgpucomp64`。已做 DDU、清 NVIDIA DX 缓存/Windows D3D 缓存；**"Game Ready 595.97 明显比更新的驱动崩溃更少"**；610.88 上几分钟连炸 3 次同一 hash。 | 中高（单报告，但栈完整；驱动回退有效是唯一被提到的缓解） |
| 1.3 | [3Dmigoto #383](https://github.com/bo3b/3Dmigoto/issues/383) | 用户半小时找不到原因、重装 Windows 都无效；**作者结论：重装驱动到"干净模式" + 关闭 NVIDIA 覆盖层后解决**。 | 中（修复方式被报告者确认有效，但未给崩溃模块名） |
| 1.4 | [3Dmigoto #180](https://github.com/bo3b/3Dmigoto/issues/180) | DarkStarSword/bo3b 明确：`allow_check_interface=1 / allow_create_device=1 / allow_platform_update=1` 是现在的推荐值；老 mod 里"强制只允许 feature level 11.0"的写法会导致崩溃。另外官方口径：**覆盖层（overlay）是已知的崩溃来源**。 | 高（上游作者原话） |
| 1.5 | [3Dmigoto #341](https://github.com/bo3b/3Dmigoto/issues/341) | 社区结论（lobotomy-x）：**"3DMigoto 和 ReShade 一起没问题；3DMigoto 和 SpecialK 不稳定；三个一起必崩"**，因为它们抢同一个 hook 点。变通：让 SpecialK/ReShade 链式加载 3DMigoto（`proxy_d3d11=` / 用 SpecialK 插件形态），或使用旧版 dxgi loader。 | 中高（多人经验一致，且与 1.6 的官方修复方向吻合） |
| 1.6 | [XXMI #218](https://github.com/SpectrumQT/XXMI-Launcher/issues/218) | 维护者 SpectrumQT 原话：**"这是 581.15 的全局驱动问题，且影响所有第三方 DLL"**（Smooth Motion 让 3DMigoto/XXMI 注入失效）。多个用户报 596.36 / 610.62 / 610.88 上仍不干净。**官方 workaround：Custom Launch 注入模式选 `Bypass`、文本框留空，Inject Libraries 依次填 `ReShade64.dll` 和 `<MI>/d3d11.dll`**（即先 ReShade 再 3DMigoto，"ReShade 的 hook 能在 Smooth Motion 之下存活"）。SpectrumQT 还宣布**用 ReShade 的 hook 体系整体替换 3DMigoto 的 Nektra hook（迁移到 MinHook + C++17）**，称可一并解决 Smooth Motion 等一大批兼容问题。 | 高（官方维护者，且已在 [XXMI 2.2.0](https://github.com/SpectrumQT/XXMI-Launcher/releases/tag/v2.2.0) 落地"改用 direct Inject，旧 hooking 方式已失效"） |
| 1.7 | [3Dmigoto #369](https://github.com/bo3b/3Dmigoto/issues/369) | "Tales of Arise + 3DMigoto，只要开着 NVIDIA Smooth Motion 就启动即崩"（仍 open，未解决）。→ NVIDIA 新驱动的"插帧/平滑"类功能与 3DMigoto 有未解决的崩溃关系。 | 中（一条报告，无 follow-up） |
| 1.8 | [Appuals: nvgpu64/nvgpucomp64 crash fix](https://appuals.com/nvgpu64-dll-nvgpucomp64-dll-crash-games/)、[windowsreport](https://windowsreport.com/nvgpucomp64-dll/) | 通用建议：DDU 重装驱动、关超频/XMP/多核增强、关 PCIe 电源管理、关后台覆盖层。**没有一条是 3DMigoto 专属的**。 | 低（泛化鸡汤文，仅作 checklist） |
| 1.9 | [Microsoft Q&A 4063389](https://learn.microsoft.com/en-us/answers/questions/4063389/what-is-causing-this-nvgpucomp64-dll-crash)、[FFXIV Lodestone 5415314](https://eu.finalfantasyxiv.com/lodestone/character/10072206/blog/5415314/) | 大量 nvgpucomp64 案例的根因是 **Intel 13/14 代 CPU + 主板默认超压（ASUS MultiCore Enhancement / MSI Lite Load / Intel ABT）**，解法是关这些选项或限制 FPS。 | 中（对本机不适用：CPU 是 9800X3D，且本机 30 天内 0 条 WHEA / 0 次蓝屏，CPU 侧不稳定证据为零） |
| 1.10 | 3DMigoto 官方配置注释（`Dependencies/d3dx.ini`） | 原文：**"We force all LoadLibrary calls back to the game folder, because games and nvidia both break the loading chain by going directly to System32."** → 3DMigoto 与 NVIDIA 的加载链冲突是上游**已知**并因此设计了 `load_library_redirect`。 | 高（上游源码/配置原话） |

**未找到**：任何把 `nvgpucomp64.dll` 明确归因于 3DMigoto 的官方 issue/公告；也没有 NVIDIA 侧承认该驱动版本存在着色器编译器缺陷的公开文书。

---

## 2. 指定仓库的 Issues / Discussions 检索结果

| 仓库 | 结果 |
|---|---|
| `SpectrumQT/XXMI-Launcher` | **`nvgpucomp64` 关键词命中 0 条**（GitHub 搜索 API 全库查询）。Endfield 相关 issue 5 条：[#343](https://github.com/SpectrumQT/XXMI-Launcher/issues/343)（ACE 反作弊 `0x80000003`，非本问题）、[#299](https://github.com/SpectrumQT/XXMI-Launcher/issues/299)（`Qt5WebEngineCore.dll` 0xc0000005，维护者判定"与 XXMI/EFMI 无关，疑似冲突软件/系统损坏"）、[#276](https://github.com/SpectrumQT/XXMI-Launcher/issues/276)（mod 冲突，2.1.5 加入 mod ini 自动清理后好转）、[#275](https://github.com/SpectrumQT/XXMI-Launcher/issues/275)、[#302](https://github.com/SpectrumQT/XXMI-Launcher/issues/302)。真正相关的 DLSS/驱动记录是 [#218](https://github.com/SpectrumQT/XXMI-Launcher/issues/218) 与 [#266](https://github.com/SpectrumQT/XXMI-Launcher/issues/266)（NVIDIA Smooth Motion 不兼容）、[#333](https://github.com/SpectrumQT/XXMI-Launcher/issues/333)（RTX 5080 上帧数暴跌，官方答复是**关掉 Debug Logging 和 Calls Logging**）、[#287](https://github.com/SpectrumQT/XXMI-Launcher/issues/287)（ReShade 与 EFMI 注入顺序，2.1.5 已修）。 |
| `SpectrumQT/EFMI-Package` | **`nvgpucomp64` 0 条、`DLSS` 0 条、`anti-cheat` 0 条**。仅 7 个 issue，最相关的是 [#1 CRASH] DX11 and overflow of RAM](https://github.com/SpectrumQT/EFMI-Package/issues/1)：DX11 路径在 **NVIDIA 50 系显卡上存在显存/内存泄漏**（对象数 17k→55k 不释放，32GB 被吃光，15–30 分钟必须重启），维护者与社区均表示"3DMigoto 只支持 DX11，无解"。 |
| `bo3b/3Dmigoto` | **`nvgpucomp64` 0 条、`DLSS` 0 条**。相关： [#369](https://github.com/bo3b/3Dmigoto/issues/369)（Smooth Motion 启动崩）、[#383](https://github.com/bo3b/3Dmigoto/issues/383)（干净重装驱动+关覆盖层解决）、[#341](https://github.com/bo3b/3Dmigoto/issues/341)（与 ReShade/SpecialK 三方 hook 冲突）、[#365](https://github.com/bo3b/3Dmigoto/issues/365)、[#180](https://github.com/bo3b/3Dmigoto/issues/180)、[#104](https://github.com/bo3b/3Dmigoto/issues/104)（锁序死锁）。 |
| `DarkStarSword/3Dmigoto` | **仓库不存在（API 404）**。上游实际只有 `bo3b/3Dmigoto`（DarkStarSword 仍在其中活跃答疑），另有多个 fork（ZXMI/XXMI 的 `SpectrumQT/XXMI-Libs-Package` 即 XXMI DLL，是"2Dmigoto"精简分支）。 |
| 旁证：`SpectrumQT/XXMI-Libs-Package` | issues 列表全为性能/INI 语法优化，**无任何崩溃类报告**，也无 nvgpucomp64 / DLSS 相关。 |
| 旁证：`NIGos/dlss5-bridge #27`、`jlrouzies-fr/DLSS5-Feeder #120` | 两条**重要的负面旁证**：在 Endfield 与 MHW 上，只要进程里出现"第二个活跃 D3D/NVAPI 设备"（Bridge 的私有 D3D12 设备 / ReShade 注入），`NVSDK_NGX_*_Init`/`CreateFeature` 就会失败甚至抛异常（`0x80000003` / `0xBAD00005`，NGX 日志：`multiple active devices present, and a device was not specified`）。**本机游戏目录里恰好躺着 `nvngx_dlssnr.dll`（165 MB）与 ReShade 的 D3D12 注入痕迹。** |

**未找到**：`SpectrumQT/XXMI-Launcher`、`SpectrumQT/EFMI-Package`、`SpectrumQT/XXMI-Libs-Package`、`bo3b/3Dmigoto` 中任何以"Endfield + nvgpucomp64"为主题的 issue 或 discussion。

---

## 3. d3dx.ini 配置项：已知冲突与推荐值

| 配置项 | 上游/XXMI 定义与默认 | 已知问题 / 推荐 | 可信度 |
|---|---|---|---|
| `load_library_redirect` | `0`=不改写；`1`=只把 `nvapi.dll` 拉回游戏目录；`2`=把 `d3d11.dll` **和** `nvapi.dll` 都拉回游戏目录。上游注释：NVIDIA 会绕过加载链直接去 System32，所以必须强制。 | **它与"必须用 DLSS"直接冲突**：值=2 时，游戏（及 DLSS 运行时）对 `nvapi.dll` 的加载会被重定向，而 NGX/DLSS 的初始化恰好依赖 NVIDIA 自己的 NVAPI 路径。**没有任何公开文档说明可以只排除 `nvngx_dlss.dll`**（见 §4 未找到）。可试的降级顺序：`2 → 1 → 0`。注意 XXMI 的上游默认就是 2，改这个属于"离开官方配置"，可能引发 mod 不生效。 | 中（机制清楚，但无人公开验证过 Endfield） |
| `allow_create_device` / `allow_check_interface` / `allow_platform_update` | 官方现代默认：`allow_check_interface=1`、`allow_create_device=1`、`allow_platform_update=1`（任意 feature level 放行）。老 mod 常带 `allow_create_device=0`/强制 11.0。 | bo3b 明确指出老的强限制写法会崩；顺序建议"先 `allow_check_interface`，再 `allow_create_device=2`，最后 `=1`"。本机已是官方值，**无需改**。 | 高（上游作者原话） |
| `track_region_hashes` | EFMI **必需** `=1`（Endfield 把索引/顶点缓冲打包成单个资源，必须靠区域哈希匹配）。XXMI 2.1.8 起由 Launcher 强制写入。 | 不要关（关了 EFMI 直接不工作）。 | 高（EFMI 1.2.0 release note 原话） |
| `track_implicit_index_buffers` | EFMI 必需 `=1`（部分 draw call 复用上一个 IB）。 | 不要关。 | 高（同上） |
| `allow_buffer_resize` | EFMI **必须** `=0`。EFMI 1.2.0 原文：**"Disabled buffer resizing support. It's not needed for Endfield and ignorant usage is causing crashes."** | 本机已是 0，**无需改**。 | 高（官方 release note，直指"会导致崩溃"） |
| `skip_early_includes_load` | XXMI/EFMI 当前模板 = **`1`**；语义：把 mod 的 ini 加载从 DLL 初始化阶段解耦，推迟到第一帧之后（"ini files load sequence during DLL init time isn't as robust as one for reload"）。 | **本机是 `0`（旧行为）**。官方注释自己就说明了旧行为更脆弱。→ 这是最值得改的一处。 | 高（配置注释即官方依据） |
| `config_initialization_delay` | 当前模板 = **`0`**（第一帧后加载）；`-1` = 关闭延迟、**模拟原始 3dmigoto 行为**。 | **本机是 `-1`**，配合 `skip_early_includes_load=0` 说明本机在用"最早期、最激进"的加载时序。建议改为 `skip_early_includes_load=1` + `config_initialization_delay=0`。 | 高（同上） |
| `dll_initialization_delay` | 默认 `0`；配置注释：**"to inject Reshade along with 3dmigoto, 150ms delay is required"**。 | 本机同时挂了 ReShade，却仍是 0（早期某次测试是 500）。若坚持"ReShade + 3DMigoto 共存"，应设 `150`（或更高）。 | 高（上游配置注释原话） |
| `[Logging] calls` / `debug` | `calls=1` 会写巨型日志（有用户报告 20 GB 的 `d3d11_log.txt`，并因此帧数从 120 掉到 10）。 | 本机 `calls = 1`、`debug = 0`。**排查完请务必改回 `calls=0`**（XXMI #333 官方答复同款建议）。 | 高（官方答复） |

---

## 4. "3DMigoto / DLSS 共存"的已知做法

**结论：不存在公开的、被验证过的"3DMigoto 与 DLSS 稳定共存"配方。** 逐条说明能找到的东西：

1. **XXMI 官方路线（最权威）**：SpectrumQT 在 [#218](https://github.com/SpectrumQT/XXMI-Launcher/issues/218) 给出的做法是**换 hook 宿主**而不是配置项：Bypass 模式 + `Inject Libraries = [ReShade64.dll, <MI>/d3d11.dll]`，让 3DMigoto 挂在 ReShade 的 hook 上，"ReShade 的 hook 能在 Smooth Motion 之下存活"。他随后宣布把整套 hook 从 Nektra 换成 MinHook（[XXMI 2.2.0](https://github.com/SpectrumQT/XXMI-Launcher/releases/tag/v2.2.0) 已把默认注入方式改成 direct Inject，注明"旧 hooking 方式已不再工作"）。可信度：高（维护者+已落地）。**注意：本机现在同时有 ReShade 6.8（甚至以 `D3D12.dll` 形态）+ 3DMigoto，正是 [#341](https://github.com/bo3b/3Dmigoto/issues/341) 里"多 hook 抢同一绘制调用"的高危组合。**
2. **把 `nvngx_dlss.dll` 加排除 / 让 3DMigoto 不 hook DLSS**：**未找到**任何 3DMigoto / XXMI 的配置项或文档支持这么做。`load_library_redirect` 只作用于 `nvapi.dll` 与 `d3d11.dll`；XXMI/EFMI 的 `ExcludeDLL` 一类的写法在四个仓库里搜索结果为 0。
3. **DLSS Swapper / 统一 `nvngx_dlss.dll` 版本**：找到相关生态（[rakanki911/DLSS5-Swapper](https://github.com/rakanki911/DLSS5-Swapper/releases/tag/v2.2.3)、[JPersson77 的 DLSS4 白名单解除脚本](https://gist.github.com/JPersson77/91a5c53af55104a2bfc5c9be32118203)），但**没有任何一条把"换 DLSS dll 版本"与 3DMigoto 崩溃联系起来**。反面证据：`DLSS5-Feeder #120`、`dlss5-bridge #27` 显示在 616.64/616.92 上，**越是第三方 DLSS/NGX 增强（RenoDX DLSS5、dlss5-bridge、nvngx_dlssnr）越容易在 D3D11/多设备场景下初始化失败或抛异常**；DLSS5oneclick 的作者甚至维护了一张"哪个 add-on 版本在哪些驱动上会 fault in the driver"的回退表（4.70 / 4.55 兜底）。→ **本机游戏目录里的 `nvngx_dlssnr.dll`（9/26 12:23 写入，紧接着 9/27 开始连崩）是头号可疑新增变量。**
4. **特定驱动版本**：只见于社区经验（见 §5），且方向一致是**回退**而不是升级。
5. **"必须保留 DLSS"前提下的唯一干净路线**：把 DLSS 交给**游戏自身的 Streamline/NGX**（即不要 RenoDX/Bridge 这类第三方 NGX 增强），并且不要让第二个 hook 框架（ReShade/SpecialK）同时在场。

---

## 5. 驱动版本相关报告（5xx / 6xx / RTX 50 系）

| 来源 | 内容 | 可信度 |
|---|---|---|
| [Dota2 #34220](https://github.com/ValveSoftware/Dota2-Gameplay/issues/34220) | **"Game Ready 595.97 崩溃明显少于更新的驱动"**；610.88 上同一 `FAILURE_ID_HASH` 几分钟连炸 3 次；`NNN.NN` 系列里越新越差。 | 中高（用户实测，未做完整哈希确认） |
| [XXMI #218](https://github.com/SpectrumQT/XXMI-Launcher/issues/218) | 581.15 起 NVIDIA 全局性地拦截第三方 DLL（3DMigoto/XXMI 全部受影响）；580.88 无此问题；596.36 部分修复；610.62 有人说好了，**维护者回复"问题仍在"**。 | 高（官方+多用户交叉） |
| [NVIDIA Dev Forum 343335](https://forums.developer.nvidia.com/t/rtx-5070-ti-nvgpucomp64-dll-exception-thrown-when-shader-uses-gl-nv-shader-sm-builtins/343335) | 同一驱动 `32.0.16.1692`（= 用户报的 616.92）在另一人机器上以完全相同的"启动后 35–55 秒"节奏崩 nvgpucomp64。 | 高（版本号与时间窗双重吻合） |
| [3Dmigoto #383](https://github.com/bo3b/3Dmigoto/issues/383) | 干净模式重装驱动 + 关 NVIDIA 覆盖层 → 解决 | 中 |
| [bo3b/3Dmigoto #369](https://github.com/bo3b/3Dmigoto/issues/369) | Smooth Motion（581.15 之后引入的驱动级插帧）开着 + 3DMigoto → 必崩 | 中 |
| 其他 | 616.56 / 616.64 有"屏幕闪烁"已知问题，由 616.86 Hotfix 修（与本崩溃无关，但说明这条驱动支线本就不干净） | 低 |

**未找到**：任何"NVIDIA 已确认/已修复该 nvgpucomp64 崩溃"的官方公告、AnyDesk/known-issues 列表条目或 hotfix 编号。

---

## 6. 最可能有效的 3 条建议（成本从低到高）

**① 改 d3dx.ini 的加载时序 + 消掉"多 hook 同场"（成本：5 分钟，零风险）**
在 `runtime\migoto\d3dx.ini` 里：
```ini
skip_early_includes_load = 1
config_initialization_delay = 0
dll_initialization_delay = 150      ; 若坚持 ReShade + 3DMigoto 共存
calls = 0                            ; 排障结束后必须关，否则日志能涨到几十 GB
```
同时**只保留一个 hook 框架**：把 9/26 新加进来的 `nvngx_dlssnr.dll` / `终末地EE.addon64` / `renodx-dlss.addon64` 先全部移出游戏目录，ReShade 若要留就只留一个（不要 `D3D12.dll` 与 3DMigoto 同场）。
依据：官方配置注释（§3）+ [3Dmigoto #341](https://github.com/bo3b/3Dmigoto/issues/341) 的多 hook 冲突结论 + [XXMI #218](https://github.com/SpectrumQT/XXMI-Launcher/issues/218) 的注入顺序经验。

**② 隔离测试：把"驱动缺陷"和"注入产物"分开（成本：20 分钟）**
三组各跑一次、只改一个变量：
- (a) 保留 EFMI 注入但**关掉游戏内 DLSS**（用 TAA/DLAA）：若不再崩 → 是 DLSS/NGX 与 hook 的组合（那 `nvngx_dlssnr.dll` 与 ReShade 必须先清掉）；若照崩 → 是驱动在编译 mod 替换后的 DXBC 时炸，走 ③。
- (b) 保留 DLSS 但注入一个**空 Mods 目录**（EFMI 仍在，无自定义着色器）：若照崩 → 崩溃点在 hook/设备包装而非 mod 着色器。
- (c) `load_library_redirect` 由 `2` 降到 `1` 或 `0`，再跑一次。
依据：EFMI [#1](https://github.com/SpectrumQT/EFMI-Package/issues/1)（DX11 路径在 50 系上的泄漏）与 §4 的多设备结论。

**③ DDU 干净重装 / 回退驱动到 595.97 一档（成本：40 分钟 + 停机）**
- 先用 DDU 在安全模式彻底清掉 616.92，**以"干净安装（不勾 GeForce Experience / NVIDIA App）"方式**装 595.97（或同代最后一个被报告"崩得少"的版本），装完删掉 `%LOCALAPPDATA%\NVIDIA\DXCache` 与 `GLCache`。
- 装完后**关闭 NVIDIA App 的 DLSS 覆盖（Override）**与 **Smooth Motion**；关掉所有覆盖层（NVIDIA 覆盖层、向日葵远控的显示驱动若可停也停）。
- 若 595.97 仍崩：重点怀疑本机的 **OrayIddDriver / MuMu 虚拟显示器 + AMD 核显** 造成的多活动设备问题（在设备管理器里临时禁用这两个虚拟显示适配器再测一次）。
依据：[Dota2 #34220](https://github.com/ValveSoftware/Dota2-Gameplay/issues/34220)（595.97 更少崩）、[3Dmigoto #383](https://github.com/bo3b/3Dmigoto/issues/383)（干净驱动+关覆盖层）、[NVIDIA Dev Forum 343335](https://forums.developer.nvidia.com/t/rtx-5070-ti-nvgpucomp64-dll-exception-thrown-when-shader-uses-gl-nv-shader-sm-builtins/343335)（同版本同症状）。

### 一并保留的旁证（用于向用户解释"为什么不是纯粹的 EFMI bug"）
- 本机 9/26 有 **6 次 `nvoglv64.dll`（OpenGL 驱动）0xc0000005**，以及 `EndfieldBase.dll`、`ucrtbase.dll` 崩溃 —— 说明这套驱动在本机上不止 DX11 一条路径不稳。
- 社区/上游均表示 **3DMigoto 与 DX11 是硬绑定**（EFMI #1、bo3b #354 的 "d3d12 please" 长期 open），而 Endfield 官方支持 Vulkan —— 想彻底摆脱这条崩溃路径，只能不用注入式 mod（如"Mod Fix"类非注入方案）。
