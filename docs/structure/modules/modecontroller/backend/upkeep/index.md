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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.897Z"
fingerprint: e472c02c5290b44df487d2c5400e208ede099a074151c0a3b9660c1a8a61680a
source:
  - path: "endfieldmodcontroller/modfix.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
