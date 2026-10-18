---
uid: b1d1100c
id: modecontroller.backend.upkeep.modfix
parent: modecontroller.backend.upkeep
tags: [repair]
name: {zh: "Mod 包修复", en: "Mod Package Repair"}
description:
  zh: >
      收拾“加载不了”的 Mod 包：随身带一个外部解包工具、先备份（备份目录 + 回收目录，带索引）、就地修复、回滚或删除 —— 永远可回退，绝不破坏性。
      
  en: >
      Repair a mod package that will not load: carry an external unpacking tool, back the mod up (to a backup dir and a trash dir with an index), fix in place, roll back, or delete — always reversible, never destructive.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.433Z"
fingerprint: a6c1c086c6ed2fce62f061a035927988b3624ed73a39770ef51be24c19c93cca
source:
  - path: "endfieldmodcontroller/modfix.py"
    line: 53
    end_line: 157
  - path: "endfieldmodcontroller/modfix.py"
    line: 156
    end_line: 349
  - path: "endfieldmodcontroller/modfix.py"
    line: 348
    end_line: 472
apis:
  - protocol: rpc
    path: "modfix.fix_mod"
    description:
      zh: >
          在临时目录里用外部工具修 Mod 包，**先整份备份原包**（库里不留残留）。
          
      en: >
          Repair a mod package in a temp directory with an external tool, backing the original up first (library left untouched).
          
  - protocol: rpc
    path: "modfix.rollback_mod"
    description:
      zh: >
          把修过的 Mod 回滚到逐字节一致。
          
      en: >
          Roll a repaired mod back, byte-for-byte.
          
  - protocol: rpc
    path: "modfix.fix_all"
    description:
      zh: >
          把整库跑一遍修复，已修过的默认跳过。
          
      en: >
          Run the whole library through the repair tool, skipping what is already fixed.
          
  - protocol: rpc
    path: "modfix.tool_status"
    description:
      zh: >
          外部修复工具在不在、现在能不能用。
          
      en: >
          Is the external repair tool present, and is it usable right now.
          
---
