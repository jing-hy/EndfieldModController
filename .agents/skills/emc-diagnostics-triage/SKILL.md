---
name: emc-diagnostics-triage
description: 用户拿 EndfieldModController 的诊断包/日志报故障时的排查路线——先看哪几个文件、怎么区分第三方噪音、崩溃怎么按 dump 分布定位、受控实验怎么做。仅在处理 D:\zmdmod\modecontroller 这个项目（《明日方舟：终末地》Mod 管理器）时使用。
---

# EndfieldModController 故障分诊

对象：`D:\zmdmod\modecontroller`。用户发来的现场通常是 `diagnostics-*.zip` + 一句现象描述。
**先看证据，再动代码**——错误归因会让用户白折腾好几轮。

## 一、先读哪几个文件（按顺序）

| 文件 | 看什么 |
| --- | --- |
| `summary.txt` | 采集总览、退出码释义、关键路径 —— 先确认"时间 / 版本 / 环境"三要素 |
| `logs/launch.log` | 我们自己那条链：注入自检 → 拉起 XXMI → 进程监视 |
| `player/Player.log` | **游戏自己写的**：判"走到哪一步"必看（崩溃前的最后一行最有价值） |
| `reshade-*.log` / `ReShade.ini` | DLSS5 / 第一人称那一侧（addon 有没有加载、shader 编译有没有报错） |
| `injection-trace.jsonl` | 各时刻（启动前 / 游戏启动后 / 退出 / 崩溃）的注入库与进程模块快照 |
| `dlss5-*` | preset、addon 位置、shader 清单、feed 日志 |

## 二、组件自己的日志优先（比静态分析快得多）

| 组件 | 日志 |
| --- | --- |
| 乳摇 SecondaryMotion | `<游戏目录>\plugin\sbm_log.txt`、`breast_probe_log.txt`（`[PLUGIN] READY` / `[PLUGIN] FAIL: initial config invalid -> DISABLED_SAFE`） |
| Poser | `<游戏目录>\plugin\poser_log.txt` |
| DLSS5-Feeder | `<数据根>\runtime\dlss5\dlss5-feed.log` |
| ReShade | `<数据根>\runtime\dlss5\ReShade.log`（`Failed to compile …` / `Source 'x.png' … was not found`） |
| 管理器自己 | `<数据根>\runtime\logs\launch.log` |

> 这类插件普遍会把"加载成功但条件不满足"的原因直接打出来。**怀疑某个注入不工作时，第一件事是读它自己的日志。**

## 三、崩溃：先做分布统计，再谈因果

- 游戏崩溃报告在 `<游戏目录>\CrashSightLog\` 或 `%LOCALAPPDATA%\...\Crashes`（`.dmp` + `Player.log`）。
- **单次"某模块崩溃"的时间相邻不等于因果**。先统计**全部 dump** 的"崩在哪个模块"分布，再下结论。
  实战教训：曾据"插件 READY 后 14 秒崩"判定插件有罪，统计 117 个 dump 后发现崩在 `sbm.dll` 的次数是 **0**（真凶是 `nvgpucomp64.dll` 47 次、`ReShade64.dll` 7 次）。
- 崩溃报告的 `SymInit` 里每行 `size:` 是**内存映像大小**（SizeOfImage），不是文件大小 —— 判文件身份/是否被替换要用**文件系统的大小或哈希**。

## 四、受控实验纪律（最容易违反的一条）

1. **冻结环境再让用户测**：把当前指纹（关键 dll 大小/哈希、注入库内容、proxy 归属、各开关值）打一份快照并告知。
2. **一次只改一个变量**。改了多个 ⇒ 用户每一次"还是不行"都不再可比。
3. 改完先自问：**这个改动会不会被别的代码路径撤销？**（例：启动自检会按配置把开关状态重放一遍）
4. 用户说"能进 / 不能进""生效 / 没效果"时，**当场记下完整环境指纹**，别事后凭记忆复原。
5. 用户给的"某个组合是好的"这类**对照事实**比自己推测值钱得多，优先当锚点。

## 五、常见现象 → 首选排查点

| 现象 | 先查 |
| --- | --- |
| 某功能"开了但没效果" | 配置里那个开关的**真实值** + 自检结果（别先怀疑自己刚做过的操作） |
| "文件明明在却报错" | 按**内容**校验（sha256 / 大小 / 必需文件清单）；本项目"存在≠正确"是头号返工点 |
| 游戏起不来 / 加载中闪退 | `Player.log` 尾部 + `d3dcompiler_47.dll` / `vulkan-1.dll` 是不是被 proxy 顶替（大小 vs 系统原版 4,524,496 / 831,488） |
| ReShade 报 shader 编译失败 / 贴图找不到 | `runtime\dlss5\reshade-shaders\{Shaders,Textures}` 里**逐个文件**核对（目录在 ≠ 文件齐） |
| 键按了没反应 | `hotkey_takeover` 是否真开着、面板是否真在 `runtime\dlss5\`（关统一管理器会顺带关锁键） |
| 面板/功能"时好时坏" | 看有没有**两个同名 addon**（ReShade 报 `already registered!` ⇒ 两个都不工作） |

## 六、判定"是不是我们负责的"

相当一部分日志噪音来自第三方，**不影响功能**，不需要改代码：
- ReShade 自身对某些 shader 的告警、上游 addon 的版本不兼容提示、反作弊服务的常规日志。
- 定性顺序：① 这条报错有没有对应的用户可见后果？② 它的来源是哪个组件（我们 / 上游）？③ 上游的问题 ⇒ 去上游提 issue（见项目 `AGENTS.md` 第三节）。

## 七、别把"读日志"变成"改环境"

排查需要复现时，优先在**副本环境**（`D:\zmdmod\modtest`）里做，别在用户正在玩的那份上试；
确需在真实环境做，先备份、只动确定目标、并留下可一键还原的路径。
