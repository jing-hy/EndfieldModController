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
      
revision: 5ad99916cdff1745b2f88ff3fa46f4116ff95157
updated_at: "2026-11-14T05:47:42.730Z"
fingerprint: e9b880b3f1d50cf0ee5ac737b642b283af5e5ab2b9a0ae0643578d00b5eb1524
source:
  - path: "endfieldmodcontroller/api.py"
    line: 4083
    end_line: 11374
  - path: "endfieldmodcontroller/api.py"
    line: 4859
    end_line: 12498
  - path: "endfieldmodcontroller/api.py"
    line: 9476
    end_line: 16143
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
