---
uid: b1d12001
id: modecontroller.backend.data.character-alias
parent: modecontroller.backend.data
tags: [characters]
name: {zh: "角色别名表", en: "Character Alias Table"}
description:
  zh: >
      维护角色别名表：解析官网干员列表页、抓取、与已知内容合并（绝不丢掉用户的修改），并同时写一份运行时副本与一份随 exe 发布的副本。
      
  en: >
      Keep the character alias table fresh: parse the official operator list page, fetch it, merge with what is already known (never dropping user edits), and write both a runtime copy and the copy shipped inside the exe.
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.803Z"
fingerprint: abb343d1fc6f44dd68d9c3132bb06024c8e5c265994679589a14ee542a6886dc
source:
  - path: "endfieldmodcontroller/character_sync.py"
    line: 58
    end_line: 172
  - path: "endfieldmodcontroller/character_sync.py"
    line: 143
    end_line: 410
  - path: "endfieldmodcontroller/character_sync.py"
    line: 338
    end_line: 520
apis:
  - protocol: rpc
    path: "character_sync.sync"
    description:
      zh: >
          从官网刷新角色表（非阻塞、24h 节流、失败静默）。
          
      en: >
          Refresh the character table from the official site (non-blocking, throttled, silent on failure).
          
  - protocol: rpc
    path: "character_sync.parse_official"
    description:
      zh: >
          把官网干员列表页解析成 名/代号/序号/美术 key。
          
      en: >
          Parse the official operator list page into name / codename / index / art key.
          
  - protocol: rpc
    path: "character_sync.combine_tables"
    description:
      zh: >
          把随包表与运行时表合并 —— 别名取**并集**，拼音别名不会被顶掉。
          
      en: >
          Merge the bundled table with the runtime one — aliases are unioned, so pinyin never gets dropped.
          
---
