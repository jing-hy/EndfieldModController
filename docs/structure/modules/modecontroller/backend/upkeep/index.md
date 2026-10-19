---
uid: b1c0b00b
id: modecontroller.backend.upkeep
parent: modecontroller.backend
tags: [repair, update]
name: {zh: "修复备份与更新", en: "Repair, Backup & Updates"}
description:
  zh: >
      长期维护：修复损坏的 Mod 包（带备份与回滚）、把库镜像到备份仓、检查并执行程序自更新，以及拉取可阻断启动的远端公告与异常预警。
      
  en: >
      Keeping things healthy over time: repair broken mod packages (with backup and rollback), mirror the library, check and apply program self-updates, and fetch remote announcements that can gate a launch.
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.884Z"
fingerprint: 754b1ccf3b85030a0084c5575e38a24b3e6f21e2dbc92afc6ebd48b6e86eca85
source:
  - path: "endfieldmodcontroller/modfix.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
