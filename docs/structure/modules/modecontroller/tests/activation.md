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
      
revision: 55d938448b4178c517e948237ce04bb8fda54fbe
updated_at: "2026-10-12T14:48:34.250Z"
fingerprint: 00d5e332557daa9eddc18868619070ca97782726f8c41a65f2e0a42827fc8f0b
source:
  - path: "tests/test_activation.py"
    line: 2
    end_line: 562
  - path: "tests/test_dependency_activation.py"
    line: 2
    end_line: 207
  - path: "tests/test_staging_integrity.py"
    line: 2
    end_line: 148
  - path: "tests/test_conflict_resolve.py"
    line: 2
    end_line: 141
apis: []
---
