# v1.1.0

本次更新集中在**启动速度**与**诊断能力**两处，另有一项功能状态变更需要说明。

## 一、修复启动时的重复解压：启动耗时从约 19 秒降到约 0.1 秒

`runtime_assets.ensure_all()` 里有一行

```python
ensure_dlssnr(config, ..., force=force or bool(fixed_items))
```

`fixed_items` 是清单中两条 `nvngx_dlssnr*` 条目（`official` 与 `sf`），**恒非空** ⇒ 该表达式**恒为真** ⇒ 每一轮 `ensure_all` 都强制重新解压 165 MB 的 `nvngx_dlssnr.dll`。

而 `ensure_all` 在同一次启动流程中最多被调用 **4 轮**（`ensure_injections` → `integrity.repair` → `initialize` → `launch`）：

```
修复前（本机实测）：第 1 轮 4.80s │ 第 2 轮 4.67s │ 第 3 轮 4.65s   ⇒ 累计约 19 秒
修复后（同一环境）：第 1 轮 0.09s │ 第 2 轮 0.00s │ 第 3 轮 0.00s
```

这 19 秒里主线程被占住，表现为：**启动时注入开关全部显示为关**（addon 文件还在 `_disabled\`，按开关归位排在后面）、**开关点不动**、**DLSS5 与 DLSS4 的互斥切换很慢**。

「按显卡架构选择正确的运行库」与「换卡/被整合包替换后自愈」这两件事由 `ensure_dlssnr()` 内部的 `_installed_matches()` 负责（marker 快路径 0 秒，marker 失效时扫一次 fatbin 约 0.1 秒），**不依赖强制重解压**。显式传入 `force=True`（依赖页「一键更新全部组件」）时仍然会真正重新解压。

## 二、启动过程显示分步进度

启动流程在若干步骤上天然需要时间（校验随包资产、重建数 GB 的 `Mods` 目录、净化游戏目录等），此前界面只显示按钮文字「正在启动…」，无法区分"正在工作"与"已经卡死"。

现在后端在关键节点写入当前阶段，前端在「一键启动」按钮下方实时显示（复用既有的 1~2 秒轮询，未新增通信通道）：

```
正在检查游戏目录与注入库…
正在检查随包组件与运行库…
正在重建 Mod 目录（按当前勾选，可能要复制较大的 Mod）…
正在准备 ReShade 底座与游戏内面板…
正在拉起 XXMI 启动器…
```

读不到阶段信息时该行整体隐藏。

## 三、诊断包补齐显卡驱动信息

两个诊断入口的内容此前不一致：崩溃包带「设备与显卡」段，而**手动导出的诊断包没有**。这导致通过手动包反馈"启动即退出"时，包内没有显卡驱动版本这一项。

现已统一：手动诊断包的 `environment.txt` 开头即为设备与显卡段（含每张卡的驱动版本号）。

## 四、游戏自带 Streamline 过旧时自动安装随包运行库

当游戏目录自带的 Streamline 版本过旧时，游戏 `Player.log` 中会出现成组的

```
ota.cpp:329[parseServerManifest] Unexpected line in manifest file
```

程序现在会读取该判据，命中时**自动安装**随包运行库（2.14.1）。此前该组件只在依赖页手动点击才会安装。

同机对照实测：旧版 Streamline 的日志中出现 10 条该报错，替换为随包 2.14.1 后为 0 条。需要注意的是，该报错与"启动后异常退出"是两件独立的事 —— 可正常进入游戏的机器日志中同样存在这 10 条。

判据未命中时行为不变：**不会**自动下载（保留"不静默下载大体积组件"的既有约定）。

## 五、日志文案修正

三处日志文案与实际语义不符，会在排查时产生误导：

| 位置 | 原文案 | 实际含义 | 现文案 |
|---|---|---|---|
| `configure_dlss5_injection()` | `DLSS5 注入 开启` | 写入 XXMI 注入库（ReShade 底座 + EFMI），为 DLSS4 / DLSS5 / 第一人称 / 游戏内面板共用 | `注入库已写入（ReShade 底座 + EFMI，DLSS4/DLSS5/第一人称共用）` |
| `nr_autostart.arm()` | `NR 自动开启: 已就位` | 仅挂上监视；真正按键在 `poll()` 中，且受 `auto_enable_nr_after_camera_hook` 约束 | `NR 自动开启: 已挂上监视（…）`，并反映开关状态 |
| `set_component_addon()` | `mfg` 被打印成「第一人称」 | DLSS4 多帧生成的开关动作 | 三个组件名逐组件写全 |

## 六、DLSS4 多帧生成在本作中不可用

「DLSS4 多帧生成」开关在本作中默认禁用，界面会显示原因。依据：

1. **游戏仅有 DX11 启动模式**，没有 DX12 模式（DX11 下会加载 `d3d12`，即 D3D11On12，但 addon 要求的是游戏以原生 D3D12 运行）；
2. **游戏内没有帧生成的倍率接口**，即游戏从不向 Streamline 提交帧生成请求；
3. addon 侧实测已完全就绪（`rewrote 2 arch gate(s) (0x1b0 -> 0x190)`、`full Blackwell framework kernels applied`、`verified mapped DLSS-G provider candidate version 310.9.1.0`、`observed Streamline DLSS-G wrapper version 2.14.1.0`），而 ReShade 日志中**没有出现 `Game request observed`**，面板显示 `MFG: Not observed`、`Frame Generation: Game/provider controlled`（非 `Active`）。

结论：该功能在本作中没有请求可接，与 addon、注入链路、驱动均无关。

**开关的其余判据完整保留**（RTX 40 系放行、RTX 50 系提示收益有限、其余型号锁定），常量 `deviceinfo.MFG_UNLOCK_DISABLED_FOR_THIS_GAME` 改回 `False` 即恢复原有行为。

## 七、其他

- `stage_and_prepare` 增加了"源与产物指纹一致则跳过复制"的判定基础（本次仅落地记录机制，实际跳过仍受既有清理策略限制）；
- 新增与本次修复对应的回归测试 26 项，均含"临时退回修复点确认测试变红"的反向验证。
