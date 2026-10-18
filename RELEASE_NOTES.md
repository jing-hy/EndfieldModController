<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.4.5

本版只更新随包的组件版本表，程序行为与上一版一致。

## 一、随包组件版本表跟随上游

「一键启动前的那道更新检查」读的是随包快照表（`endfieldmodcontroller/component_versions.json`），表过期就会漏报真实存在的新版。本版把四项跟上游对齐：

| 组件 | 旧 | 新 |
| --- | --- | --- |
| XXMI Launcher | v2.4.8 | **v2.4.9** |
| Endfield Poser | 0.5.86 | **0.5.108** |
| 次级运动插件（SecondaryMotion） | 3.1.2 | **3.2.0** |
| EndfieldJiggle（触摸 Mod） | 0.2.3 | **0.2.4** |

其余三项 —— XXMI Libraries v1.2.2、EFMI v1.4.8、ReShade 底座 6.8.0 —— 逐项与上游核对后本就是最新，未改。

## 二、上游这一轮的改动（各自发布说明的要点）

* **XXMI Launcher v2.4.9**：EFMI 的 Direct Game Launch 新增「官方启动器目录」选项（GRYPHLINK 与 Epic 安装需要它才能直启）；改进非全局启动器下的 GRYPHLINK 自动探测；损坏的 Steam 应用清单会给出可读报错。v2.4.7 / v2.4.8 另含动画背景播放、窗口缩放、Steam 清单搜索大小写修复。
* **Endfield Poser v0.5.108**（上游仍以预发布版发布）：适配新版游戏的衣物增强物理，修正骨链被重复扫描与衣物初始化等待被误判为失败的问题，并调整祀的袖子骨点、约束与惯性。
* **次级运动插件 v3.2.0**：改进过渡物理（上游按游戏 1.6 发布，release 标记为 `Endfield-1.6-available`）。
* **EndfieldJiggle v0.2.4**：角色界面与大世界统一为 `Alt + 鼠标左键` 的触摸操作，新增 `Ctrl+Shift+F9` 开关、`Ctrl+Shift+F7` 强制关闭、`Ctrl+Shift+F8` 诊断显示。

## 三、下载与安装判据未变

四个新版本的发布资产名，仍被现有判据命中：XXMI Launcher 的 Portable 包、Poser 的 `*win64.zip`（含预发布路线）、次级运动的 `-ZH-win-x64.zip`、Jiggle 的纯 Mod 包 `EndfieldJiggleEFMI-v*-win64.zip`。组件更新、本地版本识别与安装落点的逻辑均无改动。

## 四、没有变的

游戏内行为、各开关默认值与联动，以及 v1.4.4 的改动（自更新不再被运行中的下载任务吞掉、组件更新跟随 `xxmi_launcher` 指向的那份 XXMI、XXMI Libraries / EFMI 本地版本可读、诊断包新增「组件更新现场」）全部保持不变。
