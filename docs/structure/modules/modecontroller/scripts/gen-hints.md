---
uid: b1d1400f
id: modecontroller.scripts.gen-hints
parent: modecontroller.scripts
tags: [data]
name: {zh: "生成热键词表", en: "Generate Hotkey Hints"}
description:
  zh: >
      生成面板描述选项用的词表：从真实的 Mod ini 里挖变量命名规律，只留下真正有用的词。
      
  en: >
      Build the hint word table the panel uses to describe options, by mining real mod inis for variable naming patterns and keeping only the words that actually helped.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.537Z"
fingerprint: 37278f564c638cbb8f41099f5e216974ae398180da29b899ffb02377034846bf
source:
  - path: "scripts/gen_hotkey_hints.py"
    line: 1
    end_line: 125
apis:
  - protocol: rpc
    path: "scripts.gen_hotkey_hints"
    description:
      zh: >
          从真实 Mod ini 里挖变量命名规律，只留下对面板真正有用的词。
          
      en: >
          Mine real mod inis for variable-naming patterns and keep only the words that actually help the panel.
          
deps:
  - kind: call
    to: modecontroller.backend.data.hotkey-hints
    label: {zh: "供面板使用", en: "Feeds the panel"}
---
