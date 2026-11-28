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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.901Z"
fingerprint: c75127f94ddfa4c30e7c283486d0badadbc1cbb6df8c822380b581218fbf2540
source:
  - path: "scripts/gen_hotkey_hints.py"
    line: 2
    end_line: 127
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
