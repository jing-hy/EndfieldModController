---
uid: b1d1300b
id: modecontroller.web.log
parent: modecontroller.web
tags: [log]
name: {zh: "日志浮层", en: "Log Overlay"}
description:
  zh: >
      日志显示（Vue）：纯黑日志框 + 轮询依赖进度日志。
      
  en: >
      Log display (Vue): pure-black log box fed by dependency progress polling.
      
revision: b124e58720a8b882c922f28505d3d1412c494693
updated_at: "2026-11-28T17:22:47.856Z"
fingerprint: 48ef005c41cb7f2108e0c2d9b3d77446489d3e9b28dcc6d0cd5a1653ae7e58b2
source:
  - path: "frontend/src/pages/DepsPage.vue"
    line: 2
    end_line: 1486
apis:
  - protocol: rpc
    path: "web.logLine"
    description:
      zh: >
          按级别给一行日志上色，并增量追加。
          
      en: >
          Colourise one log line by severity and append it incrementally.
          
  - protocol: rpc
    path: "web.openLog"
    description:
      zh: >
          打开/关闭/刷新日志浮层（按规矩**纯黑底**、文字可选中复制）。
          
      en: >
          Open / close / refresh the log overlay (black background by rule, selectable text).
          
  - protocol: rpc
    path: "web.exportDiagnostics"
    description:
      zh: >
          导出诊断包，然后弹出“该发什么给作者”的反馈卡片。
          
      en: >
          Export a diagnostic bundle, then show the feedback card telling the user what to send.
          
deps:
  - kind: call
    to: modecontroller.backend.api.logs
    label: {zh: "读日志与打诊断包", en: "Reads logs/bundles"}
---
