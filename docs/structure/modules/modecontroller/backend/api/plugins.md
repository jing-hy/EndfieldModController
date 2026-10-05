---
uid: b1d0c00b
id: modecontroller.backend.api.plugins
parent: modecontroller.backend.api
tags: [api, plugins]
name: {zh: "子插件状态", en: "Sub-Plugin Status"}
description:
  zh: >
      启动页上那些可选子插件的状态：DLSS5 注入状态、乳摇的安装/启动、Poser 的安装/卸载/网页界面/日志尾部，以及组件 addon 开关。 ⚠️ 「拨动即装卸」的开关（乳摇 / Poser）**动作与配置一起落地**（`_persist_injection_switch`，否则界面会被旧值弹回、下次启动又装回来）；Poser 开关打开时**本地包已在位就不下载**，只补游戏目录文件（loader 缺失会跑上游向导自修复）——「关了再点开打不开」由此修好。
      
  en: >
      Status of the optional sub-plugins the launch page shows: DLSS5 injection, jiggle-physics install/launch, Poser install/uninstall/web-UI/log tail, and the component add-on toggle. Toggles apply **and** persist; opening Poser downloads nothing when the pack is already local.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.297Z"
fingerprint: f4f737f3126ceb30b7fe4eb77e658a2d448e8b85926c1be3e9f378bba509a468
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2528
    end_line: 4390
apis:
  - protocol: rpc
    path: "dlss5_status"
    description:
      zh: >
          DLSS5 注入状态（以及在这台显卡上可能不支持的原因）。
          
      en: >
          DLSS5 injection state (and why it may be unsupported on this GPU).
          
  - protocol: rpc
    path: "secondary_motion_status"
    description:
      zh: >
          乳摇物理插件的状态。
          
      en: >
          Jiggle-physics plugin status.
          
  - protocol: rpc
    path: "poser_status"
    description:
      zh: >
          摆姿插件的状态（能容忍“记录在、dll 不在”的中间态）。
          
      en: >
          Poser plugin status (tolerating the "record present, dll missing" in-between state).
          
  - protocol: rpc
    path: "poser_install"
    description:
      zh: >
          装/修摆姿插件：本地安装包**已在位就不下载**，只补游戏目录里的文件（loader 缺失时跑上游向导自修复）；本地真的没有包才去下载。这就是“关了再点开打不开”的修法。
          
      en: >
          Install/repair Poser: downloads nothing when the local pack is present — it just fixes the game-dir files (running the upstream wizard if the loader proxy is missing).
          
  - protocol: rpc
    path: "open_poser_web_ui"
    description:
      zh: >
          打开摆姿的网页界面（**从不**代它下发写操作）。
          
      en: >
          Open the Poser web UI (never sends it write operations).
          
deps:
  - kind: call
    to: modecontroller.backend.game
    label: {zh: "驱动子插件", en: "Drives sub-plugins"}
---
