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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.537Z"
fingerprint: 658e4ef897e7981823041401be449e3a82e577711d15f661186c759097a46a40
source:
  - path: "scripts/fetch_characters.py"
    line: 1
    end_line: 70
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
