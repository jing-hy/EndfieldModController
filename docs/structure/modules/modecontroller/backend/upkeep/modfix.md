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
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.227Z"
fingerprint: ae8508091c3b1d23f0ecad9cc40a2bbcc47796aebbd57b92a94e4082e5b4a053
source:
  - path: "endfieldmodcontroller/modfix.py"
    line: 79
    end_line: 88
  - path: "endfieldmodcontroller/modfix.py"
    line: 99
    end_line: 194
  - path: "endfieldmodcontroller/modfix.py"
    line: 273
    end_line: 398
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
