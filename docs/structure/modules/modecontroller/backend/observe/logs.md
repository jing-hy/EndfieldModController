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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.977Z"
fingerprint: 74d913bfb413da9b97f5a109f7253a66367002b41c46d5c250e79d2eb7945459
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 87
    end_line: 146
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 179
    end_line: 360
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5194
    end_line: 9526
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
