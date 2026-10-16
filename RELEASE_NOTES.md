<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.4.4

本版修三处与「更新」直接相关的缺陷，并让诊断包能直接回答「更新到底卡在哪一步」。

## 一、程序自更新会被运行中的下载任务静默吞掉（v1.0.2 – v1.4.3）

**现象**：界面曾提示「更新包已下载」，而 `runtime\_update\` 里只有一份 `last_check.json`：程序版本没有变化，日志里也没有任何自更新记录（既无「检查更新：…」也无「开始下载更新包 …」）。

**根因**（两处叠加）：

* `api.start_app_update()` 开头是 `if self._dep_task and running: return self.get_dependency_progress()` —— 把**另一个任务**（组件更新 / 依赖安装）的进度静默当成自更新的结果返回；`start_dependency_update()` / `start_full_update()` 同样如此；
* 前端 `UpdateBadge.vue` 的轮询以消息文本 `/已下载|完成/` 收尾，而组件更新任务正常结束的消息正是「完成」⇒ 徽章报「更新包已下载」，实际什么都没下载。

**修复**：新增 `api._dep_busy_result()`，三个入口在「已有下载任务在跑」时**如实拒绝**（`ok=False` + `busy=True` + 一句人话 + 落日志）；重复点自己仍返回进度；自更新进行中时组件入口同样拒绝。前端只认 `app_update` 任务，并且必须 `pending_apply` 才算「包已下载」；被拒绝时弹窗说明。

**影响范围**：后端那半自 v0.3.0 起即存在（表现为「点了没反应 / 显示的是别的任务的进度」）；v1.0.2 起前端叠加上误报，**v1.0.2 – v1.4.3 的正式版本都是完整形态**（含 `v1.2.3-beta`）。

## 二、组件更新现在跟随 `xxmi_launcher` 指向的那一份

`xxmi_launcher` 指向自行安装的 XXMI 时，更新（XXMI Launcher / XXMI Libraries / EFMI）此前**只装进内置副本** `runtime\builtin\XXMI`，依赖页显示的也是副本的版本 —— 于是出现「依赖页显示已是最新，实际启动用的那份还是旧版」。现在：

* 更新目标 = `xxmi_launcher` 指向的那棵 XXMI 树（`<根>\Resources\Bin\XXMI Launcher.exe`）；留空或指向内置时行为不变；
* 更新前把该份自己的 `XXMI Launcher Config.json` 读进内存、解压后原样写回（便携包里的出厂默认配置不会覆盖它）；
* XXMI Launcher 正在运行时**拒绝更新**并说明原因（避免留下半新半旧的 XXMI）；
* EFMI 的落点取 XXMI 配置里的 `importer_folder`（读不到或不可信时退回 `<XXMI 根>\EFMI`；落在 Mod 库内一律不用）；
* 依赖页在该行标出「更新会打进实际使用的那份：<路径>」。

## 三、XXMI Libraries / EFMI 的本地版本此前永远读不到

`updates._builtin_local_version()` 对这两项既读错了目录（一律读 XXMI 根），又读错了 marker 键（读 `XXMI-Libs_version`，而实际写入的键是 `version`）⇒ 本地版本恒为空串 ⇒ `update_available` 恒为 False，依赖页**永远不说这两项有新版本**。现在各自读自己安装目录里的 marker。

## 四、诊断包新增「组件更新现场」

新增 `diagnosis/update-forensics.txt`：更新目标（哪一份 XXMI、EFMI 落点）、各组件 marker 里的已装版本、实际在用那份 XXMI 的 `deployed_version` 与 `active_importer` / `importer_folder`、随包组件版本表、程序自更新缓存（`last_check.json` 的关键字段与 `applied.json`）。「更新不了」这类反馈此后不必再靠日志反推。

## 五、没有变的

游戏内行为、各开关默认值与联动，以及 v1.4.1 / v1.4.2 / v1.4.3 里的改动（内容级完整性校验、下载损坏三层检测、总闸与快捷键锁定联动、游戏本体路径自愈、组件版本表跟随上游）全部保持不变。
