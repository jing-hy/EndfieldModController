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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.333Z"
fingerprint: fff3d4b86a1aec0b9c4a847349d811b34e768d039bf477953727e8ec8adddb62
source:
  - path: "frontend/src/pages/DepsPage.vue"
    line: 1
    end_line: 1342
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
