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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.353Z"
fingerprint: 1f35462576bee354a04ba97290748b5077453c0579eb883458613a8cb800cafb
source:
  - path: "endfieldmodcontroller/modfix.py"
    line: 52
    end_line: 155
  - path: "endfieldmodcontroller/modfix.py"
    line: 155
    end_line: 347
  - path: "endfieldmodcontroller/modfix.py"
    line: 347
    end_line: 470
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
