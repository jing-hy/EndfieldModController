---
uid: b1d1400e
id: modecontroller.scripts.gen-pinyin
parent: modecontroller.scripts
tags: [data]
name: {zh: "生成拼音别名", en: "Generate Pinyin Aliases"}
description:
  zh: >
      给每个角色生成拼音别名，好让“用拼音命名的目录”也能对上中文角色名 —— 这决定了很多 Mod 到底被“认出来了”还是“未知角色”。
      
  en: >
      Generate pinyin aliases for every character so a folder named in pinyin still matches the Chinese character name — the difference between "recognised" and "unknown character" for a lot of mods.
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.288Z"
fingerprint: 8db019704f804ce71a690b5fbe0117890d6d1461ad571637d4eb05953940b932
source:
  - path: "scripts/gen_character_pinyin.py"
    line: 2
    end_line: 147
apis:
  - protocol: rpc
    path: "scripts.gen_character_pinyin"
    description:
      zh: >
          给每个角色生成拼音别名（**只在开发期**用 pypinyin，运行时不依赖它）。
          
      en: >
          Generate pinyin aliases for every character (dev-time only; the runtime never depends on pypinyin).
          
---
