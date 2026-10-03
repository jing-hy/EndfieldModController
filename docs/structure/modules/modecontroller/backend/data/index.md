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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.303Z"
fingerprint: 8487f6a552cd0110143429c3ccce9791dd4ff7420bb4652bb3d389d889db3d45
source:
  - path: "endfieldmodcontroller/character_sync.py"
  - path: "endfieldmodcontroller/sbm_data_sync.py"
  - path: "endfieldmodcontroller/hotkey_hints.py"
  - path: "endfieldmodcontroller/ini_lint.py"
---
