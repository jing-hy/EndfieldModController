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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.252Z"
fingerprint: d395cbd50158a817057382c2277cd0ed05e76529d7998e3966418282db11f388
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2589
    end_line: 4853
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2670
    end_line: 5003
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
