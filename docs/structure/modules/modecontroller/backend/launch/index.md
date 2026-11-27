---
uid: b1c0b005
id: modecontroller.backend.launch
parent: modecontroller.backend
tags: [launch]
name: {zh: "一键启动", en: "One-Click Launch"}
description:
  zh: >
      一键启动：收编手动放的 Mod、重做中转、维护 XXMI 注入库、改写 XXMI Launcher Config.json、确保签名密钥在位、补齐缺失依赖、清理残留进程、以系统默认方式拉起官方 XXMI 界面，并在之后跟踪游戏进程。
      
  en: >
      One-click launch: adopt manual mods, re-stage, maintain the XXMI injection library, rewrite XXMI Launcher Config.json, make sure the XXMI signing key exists, install missing dependencies, kill leftovers, launch the official XXMI GUI, and track the game process afterwards.
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.087Z"
fingerprint: a37b902f3c1838d9ab6da9f527cba86f1d48ecf61c1eb2068da6d3843143db4c
source:
  - path: "endfieldmodcontroller/launcher.py"
deps:
  - kind: call
    to: modecontroller.backend.activation
    label: {zh: "启动前先做中转", en: "Stages before launching"}
---
