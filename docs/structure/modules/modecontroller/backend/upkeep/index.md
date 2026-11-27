---
uid: b1c0b00b
id: modecontroller.backend.upkeep
parent: modecontroller.backend
tags: [maintenance, update]
name: {zh: "修复备份与更新", en: "Repair, Backup & Updates"}
description:
  zh: >
      长期维护：把用户移出的 Mod 放回回收区、把库镜像到备份仓、检查并执行程序自更新，以及拉取可阻断启动的远端公告与异常预警。
      
  en: >
      Keeping things healthy over time: trashing user-removed mods, mirroring the library, checking and applying program self-updates, and fetching remote announcements that can gate a launch.
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.286Z"
fingerprint: ec552a590a38601a519f00407ee69708cc52aa8552539e0230a4f12a632896b5
source:
  - path: "endfieldmodcontroller/modlib.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
