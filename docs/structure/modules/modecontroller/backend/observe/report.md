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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.531Z"
fingerprint: 1f6266d1aca64db85ba254b5d330cbcb42f96ca5d851b23e2503ed0d3713ff92
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2561
    end_line: 4797
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2642
    end_line: 4947
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
