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
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.280Z"
fingerprint: d351aa48370305d0140868566027abb4ae2bd4ce3330beaf8389955287bf7184
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 220
    end_line: 412
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 312
    end_line: 626
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5467
    end_line: 10072
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
