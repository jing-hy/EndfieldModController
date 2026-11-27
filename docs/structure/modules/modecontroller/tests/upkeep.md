---
uid: b1d15007
id: modecontroller.tests.upkeep
parent: modecontroller.tests
tags: [tests]
name: {zh: "运维与数据测试", en: "Upkeep & Data Tests"}
description:
  zh: >
      运维与数据的测试：Mod 移出库（含「修复功能已移除」的回归钉）、库备份、Poser 插件、角色表同步、乳摇参数同步、公告版本过滤，以及完整性检查链。
      
  en: >
      Tests for upkeep and data: mod removal into trash (plus a regression pin that the repair feature is gone), library backup, the Poser plugin, character-table sync, jiggle-parameter sync, alert version gating, and the integrity check chain.
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.115Z"
fingerprint: 8234555e7a48f139c5d401f66c9aab0cdbf7311b178c3ba44a383d590978ceb7
source:
  - path: "tests/test_modlib.py"
  - path: "tests/test_mod_backup.py"
    line: 2
    end_line: 268
  - path: "tests/test_poser.py"
    line: 2
    end_line: 272
  - path: "tests/test_alerts.py"
    line: 2
    end_line: 218
  - path: "tests/test_integrity.py"
    line: 2
    end_line: 214
apis: []
---
