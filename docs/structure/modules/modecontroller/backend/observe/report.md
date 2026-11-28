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
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.005Z"
fingerprint: 074b522f94b7140aa28c336795b3c4dae66913e35745baf8f6838773c8f9a078
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 3001
    end_line: 5681
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 3082
    end_line: 5831
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
