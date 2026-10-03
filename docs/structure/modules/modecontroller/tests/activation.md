---
uid: b1d15002
id: modecontroller.tests.activation
parent: modecontroller.tests
tags: [tests]
name: {zh: "激活与导入测试", en: "Activation & Import Tests"}
description:
  zh: >
      中转的测试：同角色互斥、依赖规划与内外优先级规则、压缩包与手动导入、Mod 总开关、staging 完整性修复，以及冲突处理动作。
      
  en: >
      Tests for staging: same-character exclusivity, dependency planning and the internal/external priority rules, archive and manual import, the mods master switch, staging integrity repair, and the conflict-resolve action.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.325Z"
fingerprint: 7c17ef17d78ba7005aab4759afef9954ea0344a040904a719f2ba8ada12782be
source:
  - path: "tests/test_activation.py"
    line: 1
    end_line: 560
  - path: "tests/test_dependency_activation.py"
    line: 1
    end_line: 205
  - path: "tests/test_staging_integrity.py"
    line: 1
    end_line: 146
  - path: "tests/test_conflict_resolve.py"
    line: 1
    end_line: 139
apis: []
---
