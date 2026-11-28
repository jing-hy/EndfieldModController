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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.897Z"
fingerprint: 186e221bf69a964ab6d243e366539eae8bc57d99e9ebde6e2f53cc2857f89c4d
source:
  - path: "endfieldmodcontroller/modlib.py"
  - path: "endfieldmodcontroller/modbackup.py"
  - path: "endfieldmodcontroller/updates.py"
---
