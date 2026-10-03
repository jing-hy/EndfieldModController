---
uid: b1d10003
id: modecontroller.backend.game.poser
parent: modecontroller.backend.game
tags: [poser]
name: {zh: "摆姿插件", en: "Poser Plugin"}
description:
  zh: >
      摆姿 / MMD 插件：检查载荷是否就位且与安装记录一致、缺了就跑它自带的部署向导、启用/禁用/卸载、打开它的网页界面 —— 程序只负责管理，绝不重写它。
      
  en: >
      The posing / MMD plugin: detect whether its payload is deployed and consistent with its install record, run its own deploy wizard when missing, enable/disable, remove, open its web UI — the program manages it but never reimplements it.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.305Z"
fingerprint: 45e1a6b09452ac256e51b74ecc4b4df61dfab1f833e8437933deb24ea7904c69
source:
  - path: "endfieldmodcontroller/poser.py"
    line: 151
    end_line: 198
  - path: "endfieldmodcontroller/poser.py"
    line: 198
    end_line: 394
  - path: "endfieldmodcontroller/poser.py"
    line: 394
    end_line: 586
apis:
  - protocol: rpc
    path: "poser.status"
    description:
      zh: >
          摆姿插件到底部署好了没 —— 能容忍“记录在、dll 不在”的中间态。
          
      en: >
          Is the Poser plugin really deployed — tolerating the "record present, dll missing" in-between state.
          
  - protocol: rpc
    path: "poser.ensure_injection"
    description:
      zh: >
          跑它**自带的**部署向导来安装（绝不自写一套）。
          
      en: >
          Install through Poser's own deploy wizard (never reimplement it).
          
  - protocol: rpc
    path: "poser.set_enabled"
    description:
      zh: >
          靠重命名插件 dll 来开关，**不动** loader 代理。
          
      en: >
          Enable / disable by renaming the plugin dll, leaving the loader proxy alone.
          
  - protocol: rpc
    path: "poser.open_web_ui"
    description:
      zh: >
          打开它自己的只读网页界面（127.0.0.1:18923）。
          
      en: >
          Open its read-only web UI on 127.0.0.1:18923.
          
---
