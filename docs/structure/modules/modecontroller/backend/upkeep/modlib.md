---
uid: b1d1100c
id: modecontroller.backend.upkeep.modlib
parent: modecontroller.backend.upkeep
tags: [library, trash]
name: {zh: "Mod 移出库", en: "Mod Trash / Remove"}
description:
  zh: >
      把用户主动移出的 Mod 从库里搬到 runtime\backups\mod-trash（删除 ≠ 真删，可手动找回）。2026-11-27 起不再包含任何「修复损坏 Mod / 回滚」逻辑。
      
  en: >
      Moves user-removed mods from the library into runtime\backups\mod-trash (never a real delete, recoverable by hand). Since 2026-11-27 it no longer contains any mod-repair or rollback logic.
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.126Z"
fingerprint: 07a0ba0c9b94190b8498d469e737883452aae54b8cd286a7e5f84ec68de58ac9
source:
  - path: "endfieldmodcontroller/modlib.py"
    line: 57
apis:
  - protocol: rpc
    path: "modlib.delete_mod"
    description:
      zh: >
          把一个 Mod 目录整份移到回收区（runtime\backups\mod-trash/<时间戳>/），保留全部文件。
          
      en: >
          Moves a whole mod directory into the trash folder, keeping every file.
          
---
