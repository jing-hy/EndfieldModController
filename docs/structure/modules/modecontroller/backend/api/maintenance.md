---
uid: b1d0c009
id: modecontroller.backend.api.maintenance
parent: modecontroller.backend.api
tags: [api, repair]
name: {zh: "完整性修复与配置回滚", en: "Integrity Repair & Config Rollback"}
description:
  zh: >
      修复类：完整性检查与修复、整份配置回滚，以及乳摇数据同步状态。2026-11-27 起单个 Mod 的修复/回滚接口已随功能移除。
      
  en: >
      Repairing things: the integrity check / repair pair, the whole-config rollback entry, and the jiggle-physics data sync status. Per-mod fix/rollback was removed on 2026-11-27.
      
revision: b124e58720a8b882c922f28505d3d1412c494693
updated_at: "2026-11-28T17:22:47.818Z"
fingerprint: 1b7ec7d51ca05e96c185c5dc96dd06789596407dc57c436b6c8353238ab5882d
source:
  - path: "endfieldmodcontroller/api.py"
    line: 4497
    end_line: 12890
  - path: "endfieldmodcontroller/api.py"
    line: 5285
    end_line: 14014
  - path: "endfieldmodcontroller/api.py"
    line: 10234
    end_line: 17659
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
    label: {zh: "移出库到回收区", en: "Trashes removed mods"}
---
