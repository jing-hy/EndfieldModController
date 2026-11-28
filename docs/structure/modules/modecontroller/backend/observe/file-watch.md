---
uid: b1d0f00c
id: modecontroller.backend.observe.file-watch
parent: modecontroller.backend.observe
tags: [watchdog]
name: {zh: "关键文件守护", en: "Key-File Watchdog"}
description:
  zh: >
      盯住程序依赖的关键文件：如果某一个老是被删（杀毒、别的工具），要发现、要记住哪些已经被确认过，并给出“把某个文件夹加白名单”的建议，而不是等到后面默默失败。
      
  en: >
      Keep an eye on the files the program depends on: if one keeps disappearing (antivirus, another tool), notice it, remember which ones were already acknowledged, and surface a suggestion to whitelist the folder instead of failing silently later.
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.118Z"
fingerprint: 47b81c33e1050dd8a9f960ae828a2fab141dfa07387a3244e5e399ee5278c0fc
source:
  - path: "endfieldmodcontroller/filewatch.py"
    line: 50
    end_line: 463
  - path: "endfieldmodcontroller/filewatch.py"
    line: 528
    end_line: 877
apis:
  - protocol: rpc
    path: "filewatch.scan"
    description:
      zh: >
          采样关键文件，发现哪些老是被删。
          
      en: >
          Sample the key files and notice which ones keep disappearing.
          
  - protocol: rpc
    path: "filewatch.pending"
    description:
      zh: >
          值得告诉用户的条目（在**一键启动**时问，不是开管理器时）。
          
      en: >
          Entries worth telling the user about (asked at one-click launch, not at app start).
          
  - protocol: rpc
    path: "filewatch.ack"
    description:
      zh: >
          标记为已知晓，同一条提醒不再重复弹。
          
      en: >
          Mark them as acknowledged so the same warning does not nag again.
          
---
