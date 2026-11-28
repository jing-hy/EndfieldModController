---
uid: b1c0b00c
id: modecontroller.backend.data
parent: modecontroller.backend
tags: [data, lint]
name: {zh: "角色数据与 ini 体检", en: "Character Data & Ini Lint"}
description:
  zh: >
      供其他模块读的数据表：角色别名表（官网同步 + 随包兜底 + 拼音别名）、乳摇每角色参数、面板热键词表，以及按 3DMigoto 解析规则体检生成文件的 ini 体检器。
      
  en: >
      The data tables the rest of the program reads: the character alias table (official site sync + bundled fallback + pinyin aliases), the jiggle-physics per-character parameters, the panel hotkey wording, and the ini linter that checks generated files against 3DMigoto's parsing rules.
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.735Z"
fingerprint: dec860c273531e6490d1e080869610046a0c5b4304c17256e1d3fc54c9458989
source:
  - path: "endfieldmodcontroller/character_sync.py"
  - path: "endfieldmodcontroller/sbm_data_sync.py"
  - path: "endfieldmodcontroller/hotkey_hints.py"
  - path: "endfieldmodcontroller/ini_lint.py"
---
