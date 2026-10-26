---
uid: b1d12006
id: modecontroller.backend.config.detect
parent: modecontroller.backend.config
tags: [detect]
name: {zh: "路径自动探测", en: "Path Auto-Detection"}
description:
  zh: >
      在别人机器上把东西找出来：游戏目录（配置、常见安装根、扫盘）、XXMI 启动器、旧版 migoto loader、官方启动器、乳胶物理安装位置 —— 每项都带缓存结果，启动才快得起来。
      
  en: >
      Find things on a stranger's machine: the game directory (config, common install roots, drive scan), the XXMI launcher, a legacy migoto loader, the official launcher, the jiggle-physics install — each with a cached result so startup stays fast.
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.377Z"
fingerprint: 178b4a34f8f6979ac035d7c233675dee4b03bde8c1e532cddc83ac794bcff800
source:
  - path: "endfieldmodcontroller/config.py"
    line: 1346
    end_line: 2126
  - path: "endfieldmodcontroller/config.py"
    line: 1432
    end_line: 2300
apis:
  - protocol: rpc
    path: "config.auto_detect_game_dir"
    description:
      zh: >
          找游戏目录：配置、官方启动器的 games 目录、扫盘三条路。
          
      en: >
          Locate the game across config, the official launcher's games dir, and a drive scan.
          
  - protocol: rpc
    path: "config.auto_detect_xxmi"
    description:
      zh: >
          找 XXMI 安装位置（你自己的或内置那份）。
          
      en: >
          Locate an XXMI installation (yours or the built-in one).
          
  - protocol: rpc
    path: "config.available_drives"
    description:
      zh: >
          枚举盘符 —— 于是配置里不出现任何写死的盘。
          
      en: >
          Enumerate drives, so nothing is hardcoded to one machine's layout.
          
deps:
  - kind: call
    to: modecontroller.backend.config.model
    label: {zh: "读配置字段", en: "Reads config fields"}
---
