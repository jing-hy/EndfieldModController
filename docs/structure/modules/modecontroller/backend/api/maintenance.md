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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.865Z"
fingerprint: a8beee663c03015e162cc608ced83e0519222b75d13c503401d68895127714fc
source:
  - path: "endfieldmodcontroller/api.py"
    line: 4268
    end_line: 11968
  - path: "endfieldmodcontroller/api.py"
    line: 5044
    end_line: 13092
  - path: "endfieldmodcontroller/api.py"
    line: 9773
    end_line: 16737
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
