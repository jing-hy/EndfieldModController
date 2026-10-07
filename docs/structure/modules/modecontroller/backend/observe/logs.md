---
uid: b1d0f007
id: modecontroller.backend.observe.logs
parent: modecontroller.backend.observe
tags: [logs]
name: {zh: "事件与会话日志", en: "Event & Session Logs"}
description:
  zh: >
      程序自己的日志：会话/每日/启动三份日志、结构化 log_event 行、异常捕获、系统与运行时快照，以及那份“游戏到底加没加载我们中转的文件”的 EFMI 状态转储。
      
  en: >
      The program's own log files and how they are written: session / daily / launch logs, structured log_event lines, exception capture, system and runtime snapshots, and the EFMI state dump that says whether the game actually loaded our staged files.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.250Z"
fingerprint: d9ab0d41256f753d5e9c4d4db52567cc9817f2af2f69ba20f1a24361c4434b8f
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 87
    end_line: 146
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 179
    end_line: 360
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5272
    end_line: 9682
apis:
  - protocol: rpc
    path: "log_event"
    description:
      zh: >
          往当日日志追加一行结构化事件。
          
      en: >
          Append one structured event line to the daily log.
          
  - protocol: rpc
    path: "log_system_info"
    description:
      zh: >
          会话开始时记下系统事实（系统、显卡、驱动）。
          
      en: >
          Log system facts (OS, GPU, driver) at session start.
          
  - protocol: rpc
    path: "log_efmi_state"
    description:
      zh: >
          记下 EFMI 的持久变量 —— 判断“游戏到底加载了我们的中转文件没”靠的就是它。
          
      en: >
          Log the EFMI persisted variables — the way to tell whether the game really loaded our staged files.
          
---
