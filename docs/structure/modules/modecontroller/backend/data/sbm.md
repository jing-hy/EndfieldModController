---
uid: b1d12002
id: modecontroller.backend.data.sbm
parent: modecontroller.backend.data
tags: [data]
name: {zh: "乳摇参数同步", en: "Jiggle Parameter Sync"}
description:
  zh: >
      把乳摇参数表与上游同步：解析上游发布的表、按角色合并、写到插件会读的位置，并报告已装数据是不是最新的。
      
  en: >
      Sync the jiggle-physics parameter table with its upstream source: parse the published table, merge per character, write it to the places the plugin reads, and report whether the installed data is current.
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.861Z"
fingerprint: 3659113ac0689b09c1e45975af4afb033c4cf7ddd01fbee772eb9f865586fbc5
source:
  - path: "endfieldmodcontroller/sbm_data_sync.py"
    line: 65
    end_line: 171
  - path: "endfieldmodcontroller/sbm_data_sync.py"
    line: 173
    end_line: 320
apis:
  - protocol: rpc
    path: "sbm_data_sync.sync"
    description:
      zh: >
          拉上游乳摇参数：只补我们缺的角色、**保留用户调过的值**、绝不碰 `presets/User.json`。
          
      en: >
          Pull upstream jiggle parameters: add characters we lack, keep the user's tuned values, never touch presets/User.json.
          
  - protocol: rpc
    path: "sbm_data_sync.status"
    description:
      zh: >
          报告本地乳摇数据是不是最新的。
          
      en: >
          Report whether the local jiggle data is current.
          
deps:
  - kind: call
    to: modecontroller.backend.data.character-alias
    label: {zh: "合并角色表", en: "Merges char table"}
---
