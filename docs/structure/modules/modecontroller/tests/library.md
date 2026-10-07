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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.545Z"
fingerprint: 1179f9de737e63f4de54cd9eb815296462c67a715489290b9cd4e383106b4aaf
source:
  - path: "tests/test_core.py"
    line: 1
    end_line: 121
  - path: "tests/test_scan_library_layout.py"
    line: 1
    end_line: 91
  - path: "tests/test_character_match.py"
    line: 1
    end_line: 133
  - path: "tests/test_library_safeguard.py"
    line: 1
    end_line: 131
apis: []
---
