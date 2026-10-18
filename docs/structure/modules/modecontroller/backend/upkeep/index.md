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
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.930Z"
fingerprint: 5ed605af2c794a975ea7112e041128f00648df8edc7454ddbf64d1ca9c0b9598
source:
  - path: "endfieldmodcontroller/modfix.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
