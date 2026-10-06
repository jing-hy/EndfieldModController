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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:01.009Z"
fingerprint: 067d3cbdb87e1e47c1e1bd69983bc829cecd0c67e9c5090fc6f2c0e850489105
source:
  - path: "frontend/src/pages/DepsPage.vue"
    line: 1
    end_line: 1640
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
