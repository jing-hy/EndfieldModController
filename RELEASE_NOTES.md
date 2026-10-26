<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.4.9

本版两件事：**程序被放在桌面运行时会自己搬家**（桌面不再被 config / runtime / assets 铺满），以及**发版检查现在会为"查不了随包资产"报警**；顺带修掉 `--cli` 在中文控制台崩溃的老问题。

## 一、在桌面运行 → 自动搬到 D 盘再启动

* 触发条件：**打包后的 exe**，且它的数据根（也就是 exe 所在目录）**正好是桌面**。源码运行不触发。
* 动作：优先在 `D:\EndfieldModController` 建目录，D 盘不存在或写不进去（只读 / 被策略限制）就回退 `C:\EndfieldModController`；把 exe 复制进去；在桌面建 `EndfieldModController.lnk`；用独立进程启动新位置那份，然后**原实例立刻退出**（在抢单实例锁、建窗口之前就退，不会出现两个窗口）。
* 新实例启动后，会把**桌面上那份旧 exe 删掉**（后台线程带重试，等桌面进程松手），桌面上只留快捷方式。
* 防循环：新实例带着 `EMC_RELOCATED=1` 启动，判定"已经搬过"就不再搬；从快捷方式正常启动也不会搬。
* 搬不动时不挡人：照常在原处启动，界面提示一句"没搬成：程序还在桌面"并写明原因，同时在目标目录写 `relocate.log` 留痕。
* 边界：**`library\`（用户的 Mod 库）永远不删**；搬迁只动 exe 本体，桌面已有的旧数据目录不会自动清理。

## 二、发版检查：查不了随包资产就报警

* `scripts\check_component_versions.py` 现在把"**探测不到随包资产**"当成**问题**报出来（`missing`），并**中止构建**，而不是悄悄跳过。
* 起因：`*.dll` 不进 git，所以换一台机器 clone 下来时 `assets\secondary_motion\plugin\sbm.dll` 根本不存在 —— 旧逻辑会静默跳过"表 vs 货"这一道，等于发出去一个自己都没核过的包。
* 报警文案会写清怎么办（从 `assets-bundle.zip` 解开，或按上游重放一次）；确实只想研究源码、手上没有资产包的机器可以加 `--allow-missing-assets` 放过（状态记为 `absent`，照样打印出来）。
* 不参与这道检查的仍是"联网安装"的组件（XXMI / EFMI / Poser / reshade 等）—— 那叫"不归这道管"，不叫"查不了"。

## 三、修 `--cli` 在中文控制台崩溃

* `EndfieldModController.exe --cli` 的输出里有 `⇒` 之类的字符，在 GBK 控制台上会直接抛 `UnicodeEncodeError` 把诊断命令干掉。现在先把标准输出切成 UTF-8 + `errors="replace"` 再打印。

## 四、没有变的

游戏内行为、各开关默认值与联动、Mod 库只读红线、Mod 修复规则，以及 v1.4.8 的全部改动保持不变。
