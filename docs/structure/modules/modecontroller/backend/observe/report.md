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
      
revision: 0f41bf214f75c051e693ed36eb4bd6478655242e
updated_at: "2026-10-16T14:11:18.089Z"
fingerprint: 9a4616442ca5219303056cf8f17ca406fc6d04688508e08dc170c69ca2597894
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2741
    end_line: 5157
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2822
    end_line: 5307
apis:
  - protocol: rpc
    path: "write_report"
    description:
      zh: >
          写人读的崩溃/退出报告 —— 每条事实带出处，不写猜测。
          
      en: >
          Write the human-readable crash/exit report — every fact with its source, no speculation.
          
---
