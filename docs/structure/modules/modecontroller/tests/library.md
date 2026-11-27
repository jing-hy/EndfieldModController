---
uid: b1d15001
id: modecontroller.tests.library
parent: modecontroller.tests
tags: [tests]
name: {zh: "库与解析测试", en: "Library & Parsing Tests"}
description:
  zh: >
      库层的测试：目录布局扫描、ini 解析、角色匹配与别名、辅助 Mod 识别、“名字像依赖”那条判据、把文件已消失的条目剔掉，以及“绝不碰库本身”的护栏。
      
  en: >
      Tests for the library layer: folder layout scanning, ini parsing, character matching and aliases, assist-mod detection, the "looks like a dependency" rule, pruning entries whose files vanished, and the guard that refuses to touch the library itself.
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.114Z"
fingerprint: ab8890e62d5d7a5c712e0b4483eab57cf3153ef88edde583de0c759fa5c72bef
source:
  - path: "tests/test_core.py"
    line: 2
    end_line: 123
  - path: "tests/test_scan_library_layout.py"
    line: 2
    end_line: 93
  - path: "tests/test_character_match.py"
    line: 2
    end_line: 135
  - path: "tests/test_library_safeguard.py"
    line: 2
    end_line: 133
apis: []
---
