---
uid: b1d0c009
id: modecontroller.backend.api.maintenance
parent: modecontroller.backend.api
tags: [api, repair]
name: {zh: "修复与回滚", en: "Repair & Rollback"}
description:
  zh: >
      修复类：完整性检查与修复、单个 Mod 的修复/回滚（含批量进度）、整份配置回滚，以及乳摇数据同步状态。
      
  en: >
      Repairing things: the integrity check / repair pair, per-mod fix and rollback with bulk progress, the whole-config rollback entry, and the jiggle-physics data sync status.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.330Z"
fingerprint: ccf7e6da62fbc5fd85c1836a1d4e69d7b5520a7f3320ac3dddf0ca06aae773bb
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2959
    end_line: 7620
  - path: "endfieldmodcontroller/api.py"
    line: 3735
    end_line: 8744
  - path: "endfieldmodcontroller/api.py"
    line: 7599
    end_line: 12389
apis:
  - protocol: rpc
    path: "check_integrity"
    description:
      zh: >
          跑整条自检链，返回逐项结果。
          
      en: >
          Run the whole self-check chain and return per-item results.
          
  - protocol: rpc
    path: "repair_integrity"
    description:
      zh: >
          修复入口：复用与一键启动**完全相同**的那条链。
          
      en: >
          Repair entry: re-runs the exact same chain as one-click launch.
          
  - protocol: rpc
    path: "fix_mod"
    description:
      zh: >
          修复单个 Mod 包（先备份、用外部工具、可回滚）。
          
      en: >
          Repair one mod package (backup first, external tool, rollback available).
          
  - protocol: rpc
    path: "rollback_mod"
    description:
      zh: >
          把修过的 Mod 回滚到修复前的逐字节状态。
          
      en: >
          Roll a repaired mod back to its pre-repair bytes.
          
  - protocol: rpc
    path: "fix_all_mods"
    description:
      zh: >
          批量修复，带进度轮询。
          
      en: >
          Bulk repair with progress polling.
          
  - protocol: rpc
    path: "rollback"
    description:
      zh: >
          整份配置的回滚入口。
          
      en: >
          Whole-config rollback entry.
          
deps:
  - kind: call
    to: modecontroller.backend.selfcheck
    label: {zh: "跑自检链", en: "Runs the checks"}
  - kind: call
    to: modecontroller.backend.upkeep
    label: {zh: "修 Mod 包", en: "Fixes mods"}
---
