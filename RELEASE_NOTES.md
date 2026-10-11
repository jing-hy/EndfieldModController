<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# v1.3.0

本次更新把随包组件版本表同步到上游最新。

## 一、随包组件版本表同步上游最新

### 这张表是干什么的

「一键启动」前要判断内置组件（XXMI / XXMI-Libs / EFMI / Endfield Poser）本地那份是不是最新。早期实现是每次启动都联网查 GitHub，实测一次要 6.1 秒 —— 也就是每次点「一键启动」都得先干等 6 秒。现改为读随包快照 `endfieldmodcontroller/component_versions.json`，微秒级返回；代价是这张表随管理器发版而更新，所以每次发版都联网核对一遍（`scripts/check_component_versions.py`，已内置进发版流程，对不上会中止构建）。

### 本次同步的两项

| 组件 | 表内旧值 | 表内新值 | 上游仓库 |
|---|---|---|---|
| XXMI Launcher | v2.4.1 | **v2.4.6** | SpectrumQT/XXMI-Launcher |
| Endfield Poser | 0.5.57 | **0.5.58** | OedoSoldier/Endfield-Poser |

其余四项核对后与上游一致，未改动：XXMI-Libs v1.2.2、EFMI v1.4.8、ReShade 6.8.0、SecondaryMotion 3.1.2。

### 升级后的表现

- **依赖页**：「一键更新全部组件」会把这些组件升级到上表版本；
- **一键启动**：本地版本落后且开着「自动更新依赖」时才真正下载，否则只提示存在新版并引导到依赖页 —— 下载不会静默拖慢启动流程；
- 表里留空的条目会被跳过，旧版程序读不到这张表时检查直接跳过，不会报错也不会阻塞启动。
