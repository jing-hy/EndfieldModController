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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.046Z"
fingerprint: d6da2d78e8e74533cf62f56410aedd8e735f25e10844e43bb7b754edef6088a8
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2651
    end_line: 4977
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2732
    end_line: 5127
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
