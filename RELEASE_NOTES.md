<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.4.6

本版更新内置的 RabbitFX 前置，并把它接进三处更新检查。

## 一、内置 RabbitFX 升到 v2.8

随包分发的 EFMI RabbitFX（作者 caverabbit，[GameBanana 651557](https://gamebanana.com/mods/651557)，CC BY-NC-ND 4.0）从 **v2.6**（`v26_b2546.zip`）升到 **v2.8**（`28_2d258.zip`，6,204 B）。

上游这一版在 `RabbitFX.ini` 里新增 `CommandListCleanTextures` 纹理清理通道，并放宽了 shader 正则对 `dCB3` / `dCB4` / `dCB5` 槽位的匹配；`README.txt`、`deltaTime.ini`、`DISABLED/ShaderCacheSettings.ini` 与上一版逐字节相同。

启动时的展开逻辑（`<Mod 库>/_deps/RabbitFX`）新增**安全升级**：

* 只有目录里受管文件的 sha256 **逐一对得上随包记录的历史代**（即确认是程序自己铺的那份）才会就地升级；
* 升级前整份备份到 `runtime/backups/rabbitfx/<时间戳>/`（带 `backup.json` 清单，可还原）；
* 用户自己放的那份、或改过的 ini，一律不动，自检里如实写「保留不动」；
* 目录里多出来的文件（例如自己启用了 shader cache 而放进来的 `ShaderCacheSettings.ini`）在升级时保留。

## 二、修 GameBanana 选文件的判据

依赖链条用 `file_name_contains` 钉的是**具体文件名**，上游每发一版都会换名字。旧实现在名字匹配不上时会退化成「取页面上最新的文件」，而同一页面上还挂着 `examples.zip`（1.9 MB 示例包）与 `cnmodfixer…zip`（9.6 MB 工具 exe），它们恰恰是最后上传的 —— 结果就是「依赖更新」把示例包或工具装进 `_deps/RabbitFX`。

现在：名字匹配不上时优先选作者标注的 **Main File**；没有标注时排除描述里带「示例 / 演示 / 工具 / 修复器 / 实验版」字样的文件；仍然挑不出来就**报错并列出页面上的文件名**，不再装一个猜出来的东西。归档文件一律不选。

## 三、RabbitFX 接进三处更新检查

| 检查 | 位置 | 判据 |
| --- | --- | --- |
| 发布前 | `scripts/check_component_versions.py --strict` | 联网核对 `component_versions.json` 里登记的 `rabbitfx` 版本与 GameBanana 当前主文件是否一致 |
| 启动前 | `pending_component_updates`（一键启动前的本地比对） | 读同一张表 + 本机 `_deps/RabbitFX` 的版本（从 ini 首页注释解析） |
| 下载更新 | `check_updates`（依赖页/设置页的「检查更新」） | 联网查 GameBanana 当前主文件版本，给出 `update_available` 与下载地址 |

另外修掉一处一直存在、这次接组件时才发现的问题：「检查组件更新」与依赖页的「检查状态」都把结果当成空列表显示 —— 接口只返回分段 dict，而界面找的是 `components`。现在接口同时给出一份列表，两个入口都能看到每个组件当前版本与是否有新版。

## 四、没有变的

游戏内行为、各开关默认值与联动、Mod 库只读红线，以及 v1.4.5 的改动（随包组件版本表跟随上游：XXMI v2.4.9 / Poser 0.5.108 / SecondaryMotion 3.2.0 / EndfieldJiggle 0.2.4）全部保持不变。
