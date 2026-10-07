---
uid: b1c0b00b
id: modecontroller.backend.upkeep
parent: modecontroller.backend
tags: [repair, update]
name: {zh: "修复备份与更新", en: "Repair, Backup & Updates"}
description:
  zh: >
      长期维护：用外部工具修复损坏的 Mod 包（带备份与回滚）、把库镜像到备份仓、检查并执行程序自更新，以及拉取可阻断启动的远端公告与异常预警。
      
  en: >
      Keeping things healthy over time: repair broken mod packages with an external tool (with backup and rollback), mirror the library into a backup repo, check for and apply program self-updates, and fetch the remote announcements/threat alerts that can gate a launch.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.535Z"
fingerprint: a0388b4d67925d2f4119b5be21af9afac3a05319572ce4c0f3475f9d551f6ed3
source:
  - path: "endfieldmodcontroller/modfix.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
