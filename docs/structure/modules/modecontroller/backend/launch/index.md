---
uid: b1c0b005
id: modecontroller.backend.launch
parent: modecontroller.backend
tags: [launch]
name: {zh: "一键启动", en: "One-Click Launch"}
description:
  zh: >
      一键启动：收编手动放的 Mod、重做中转、维护 XXMI 注入库、改写 XXMI Launcher Config.json、确保签名密钥在位、补齐缺失依赖、清理残留进程、以无界面方式（--nogui --xxmi EFMI）直接拉起游戏，并在之后跟踪游戏进程。
      
  en: >
      One-click launch: adopt manual mods, re-stage, maintain the XXMI injection library, rewrite XXMI Launcher Config.json, make sure the XXMI signing key exists, install missing dependencies, kill leftovers, start the game headlessly through XXMI (--nogui --xxmi EFMI), and track the game process afterwards.
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:56.997Z"
fingerprint: 3157c48139c85ce9af179ef5b8b380ae1aade7329205bd4bf4ce61b20d5894a9
source:
  - path: "endfieldmodcontroller/launcher.py"
deps:
  - kind: call
    to: modecontroller.backend.activation
    label: {zh: "启动前先做中转", en: "Stages before launching"}
---
