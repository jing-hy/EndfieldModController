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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.055Z"
fingerprint: 2a19bbf620a09f5ba0149d20b469700bce55628c795a2888c48a79c851a4f043
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
