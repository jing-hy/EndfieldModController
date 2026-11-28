---
uid: b1d0f006
id: modecontroller.backend.observe.report
parent: modecontroller.backend.observe
tags: [report]
name: {zh: "报告渲染", en: "Report Rendering"}
description:
  zh: >
      渲染人读的崩溃/退出报告：进程存活时间、注入快照、XXMI 注入记录、CrashSight 摘要、游戏崩溃栈片段与 Player.log 尾部 —— 每条事实都带出处，不写猜测。
      
  en: >
      Render the human-readable crash/exit report: process lifetime, injection snapshot, XXMI injection records, CrashSight summary, the game's crash stack excerpt, and the Player.log tail — every fact with its source, no speculation.
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.887Z"
fingerprint: 9112e4a8695909130afe36250c9b5b986c41480fbad2baa07b8035ac11747cb4
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2831
    end_line: 5337
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2912
    end_line: 5487
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
