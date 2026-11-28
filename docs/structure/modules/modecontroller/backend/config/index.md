---
uid: b1c0b002
id: modecontroller.backend.config
parent: modecontroller.backend
tags: [config]
name: {zh: "配置与路径", en: "Config & Paths"}
description:
  zh: >
      配置模型与路径推导：AppConfig 数据类（库/运行/中转/游戏目录路径与几十个开关）、原子写与损坏配置隔离、老配置迁移，加上磁盘小工具（原子写、Mod 库重叠护栏）与全项目唯一的版本号/仓库常量。
      
  en: >
      Configuration model and path derivation: the AppConfig dataclass (library/runtime/staging/game paths, dozens of switches), atomic save with corruption quarantine, old-config migration, plus disk helpers (atomic writes, library-overlap guard) and the single source of version/repo constants.
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.106Z"
fingerprint: 2ec5f66711db9713aa8a6b88b6e813d2ee842cd80576cac3c55e67fb86b8fa82
source:
  - path: "endfieldmodcontroller/config.py"
  - path: "endfieldmodcontroller/fsutil.py"
  - path: "endfieldmodcontroller/version.py"
---
