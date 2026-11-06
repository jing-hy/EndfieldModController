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
      
revision: 6956df017aaf625c5a15ea64c5d6f1d0f5ac2bd4
updated_at: "2026-11-06T13:05:30.460Z"
fingerprint: 5c445c40c7fdb8217caacab0754633f8d22fba911623c0f69c09d9d10b2fc41c
source:
  - path: "endfieldmodcontroller/modfix.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
