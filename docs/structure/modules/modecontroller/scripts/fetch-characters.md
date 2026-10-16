---
uid: b1d1400d
id: modecontroller.scripts.fetch-characters
parent: modecontroller.scripts
tags: [data]
name: {zh: "拉取角色表", en: "Fetch Character Table"}
description:
  zh: >
      抓官网干员列表并生成随包的角色表 —— 新装的程序不必联网就已经认识所有角色。
      
  en: >
      Fetch the official operator list and turn it into the bundled character table, so a fresh install already knows every character without a network round trip.
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.054Z"
fingerprint: ce863baf65d299d995d71447616456ca56b6d625dcd6cb2da9a7cb45f7a267f4
source:
  - path: "scripts/fetch_characters.py"
    line: 2
    end_line: 72
apis:
  - protocol: rpc
    path: "scripts.fetch_characters"
    description:
      zh: >
          抓官网干员列表，刷新随包角色表。
          
      en: >
          Fetch the official operator list and refresh the bundled character table.
          
deps:
  - kind: call
    to: modecontroller.backend.data.character-alias
    label: {zh: "写角色表", en: "Writes char table"}
---
