---
uid: b1d12003
id: modecontroller.backend.data.hotkey-hints
parent: modecontroller.backend.data
tags: [wording]
name: {zh: "面板词表", en: "Panel Wording"}
description:
  zh: >
      把 Mod 的变量名翻成人话：分词、过滤噪声词、拼出短语，实在认不出时退回可读的按键名 —— 面板能说“开大后”而不是甩一串变量名，靠的就是它。
      
  en: >
      Turn a mod's variable names into words a player understands: tokenise names and mesh hints, filter noise words, assemble a phrase, and fall back to a readable key name when nothing meaningful is found — this is what makes the panel say "开大后" instead of a variable dump.
      
revision: 55d938448b4178c517e948237ce04bb8fda54fbe
updated_at: "2026-10-12T14:48:34.212Z"
fingerprint: c6685abd40f693261e08bed42c061ce699aceda7d0baaf6da0e7b5d379228646
source:
  - path: "endfieldmodcontroller/hotkey_hints.py"
    line: 185
    end_line: 298
  - path: "endfieldmodcontroller/hotkey_hints.py"
    line: 297
    end_line: 482
apis:
  - protocol: rpc
    path: "hotkey_hints.hint_for"
    description:
      zh: >
          把一条 Mod 变量变成玩家看得懂的短语（认不出就退回按键名，**绝不编造**）。
          
      en: >
          Turn one mod variable into a phrase a player understands (falls back to the key name, never invents).
          
  - protocol: rpc
    path: "hotkey_hints.key_label"
    description:
      zh: >
          把键码变成可读标签（`KEY_RIGHT` → `→`）。
          
      en: >
          Readable label for a key code (KEY_RIGHT → →).
          
  - protocol: rpc
    path: "hotkey_hints.mesh_tokens"
    description:
      zh: >
          一个 Mod 名或变量指向哪些部位/网格。
          
      en: >
          Which mesh/part tokens a mod name or variable refers to.
          
---
