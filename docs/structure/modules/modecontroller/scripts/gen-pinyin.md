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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.537Z"
fingerprint: b8485b15954c0f05db07bbdd755fb7ef9b3964cda8daebbb28e1174543a44966
source:
  - path: "scripts/gen_character_pinyin.py"
    line: 1
    end_line: 145
apis:
  - protocol: rpc
    path: "scripts.gen_character_pinyin"
    description:
      zh: >
          给每个角色生成拼音别名（**只在开发期**用 pypinyin，运行时不依赖它）。
          
      en: >
          Generate pinyin aliases for every character (dev-time only; the runtime never depends on pypinyin).
          
---
