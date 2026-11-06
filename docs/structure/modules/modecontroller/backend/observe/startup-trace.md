---
uid: b1d0f013
id: modecontroller.backend.observe.startup-trace
parent: modecontroller.backend.observe
tags: [diagnostics, startup, performance]
name: {zh: "启动时间线", en: "Startup Timeline"}
description:
  zh: >
      在启动链的六个时刻各记一个点（进程创建 → 进入 main → API 构造 → 窗口创建 → 前端桥就绪 → 首屏 get_state 返回），拼成一行人话写进日志。专治「启动慢，但说不清慢在哪一段」：onefile 解压、窗口与 WebView2、首屏取数三段归属完全不同，只有分开量才定得住改哪。打点本身不做 IO，写日志失败一律静默。
      
  en: >
      Records six marks along the startup chain (process creation, entering main, API construction, window creation, frontend bridge ready, first get_state return) and writes one human-readable line to the log. It exists to answer 'startup is slow, but which part?' — onefile extraction, window/WebView2 init, and the first state fetch have very different owners. Marking does no IO and log failures are silent.
      
revision: 6956df017aaf625c5a15ea64c5d6f1d0f5ac2bd4
updated_at: "2026-11-06T13:05:30.451Z"
fingerprint: 75bfaffa4ce2e5aae3020f0c7b9f4b24feb48e868758f4c35984d01d83a5aa08
source:
  - path: "endfieldmodcontroller/startup_trace.py"
    line: 1
apis:
  - protocol: rpc
    path: "mark"
    description:
      zh: >
          记一个时间点（距本模块导入多少秒）。
          
      en: >
          Record one mark relative to module import.
          
  - protocol: rpc
    path: "mark_once"
    description:
      zh: >
          只在第一次记同一个点（两条路径都可能先到时不互相覆盖）。
          
      en: >
          Record a mark at most once (two paths may race).
          
  - protocol: rpc
    path: "process_uptime_seconds"
    description:
      zh: >
          从进程创建到现在的秒数，取不到返回 None。
          
      en: >
          Seconds since process creation, or None when unavailable.
          
  - protocol: rpc
    path: "summary"
    description:
      zh: >
          各打点的绝对时刻（缺项为 None）。
          
      en: >
          Absolute timestamps of every mark (None when missing).
          
  - protocol: rpc
    path: "report_line"
    description:
      zh: >
          拼成一行人话，供启动日志用。
          
      en: >
          Compose the one-line startup report.
          
---
