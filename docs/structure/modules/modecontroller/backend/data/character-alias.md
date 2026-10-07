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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.336Z"
fingerprint: 11e0872147e65d7ec64ecfa761263ceaaf797fd54a354eb4c1ea497f998d8756
source:
  - path: "endfieldmodcontroller/character_sync.py"
    line: 57
    end_line: 136
  - path: "endfieldmodcontroller/character_sync.py"
    line: 127
    end_line: 306
  - path: "endfieldmodcontroller/character_sync.py"
    line: 286
    end_line: 416
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
