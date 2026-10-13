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
      
revision: d6153bf31b870c1ccd2e00dac49af51793b5267a
updated_at: "2026-10-13T16:02:57.659Z"
fingerprint: d6da2d78e8e74533cf62f56410aedd8e735f25e10844e43bb7b754edef6088a8
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2648
    end_line: 4971
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2729
    end_line: 5121
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
