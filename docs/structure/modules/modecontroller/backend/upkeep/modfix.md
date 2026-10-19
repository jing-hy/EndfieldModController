---
uid: b1d1100c
id: modecontroller.backend.upkeep.modfix
parent: modecontroller.backend.upkeep
tags: [repair]
name: {zh: "Mod 包修复", en: "Mod Package Repair"}
description:
  zh: >
      Mod 修复（实验性）：把该 Mod 的 .ini 里所有 ps-tN（N<21）整体 +1（ps-t0→ps-t1、ps-t01→ps-t02），先整份备份、可回滚；备份目录 + 回收目录带索引。不再使用任何外部工具。
      
  en: >
      Mod repair (experimental): shifts every ps-tN (N<21) in the mod's .ini files up by one, backing the mod up first and keeping a rollback index. No external tool is used anymore.
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.884Z"
fingerprint: 0746b5f00822271ad4f6c7feb0f31aefb15c1bfb8203148c303440ed083e6e2e
source:
  - path: "endfieldmodcontroller/modfix.py"
    line: 64
    end_line: 99
  - path: "endfieldmodcontroller/modfix.py"
    line: 116
    end_line: 274
  - path: "endfieldmodcontroller/modfix.py"
    line: 307
    end_line: 413
apis:
  - protocol: rpc
    path: "modfix.fix_mod"
    description:
      zh: >
          把该 Mod 的 ps-tN（N<21）整体 +1：先整份备份，已修过默认拒绝（force 才再 +1）；这不是正规修法。
          
      en: >
          Shift every ps-tN (N<21) up by one after a full backup; already-fixed mods need force.
          
  - protocol: rpc
    path: "modfix.rollback_mod"
    description:
      zh: >
          用最近一次修复前的备份还原（逐字节一致），并消费掉那条备份。
          
      en: >
          Restore from the latest pre-fix backup, byte-for-byte, consuming that backup.
          
---
