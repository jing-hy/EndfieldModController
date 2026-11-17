---
uid: b1d0c00c
id: modecontroller.backend.api.logs
parent: modecontroller.backend.api
tags: [api, logs]
name: {zh: "日志与诊断包", en: "Logs & Bundles"}
description:
  zh: >
      界面侧的日志与打包：读/清启动日志、读控制器日志、导出诊断包，以及把前端报错接住的入口（不让界面崩在虚空里）。
      
  en: >
      Logs and bundles from the UI: read / clear the launch log, read the controller log, export a diagnostic bundle, and the frontend error sink that keeps UI crashes out of the void.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.085Z"
fingerprint: dec7b43f248ee7b4af5bb1f516376b77c781761cd34d9948f3081365280ec985
source:
  - path: "endfieldmodcontroller/api.py"
    line: 906
    end_line: 4361
  - path: "endfieldmodcontroller/api.py"
    line: 4236
    end_line: 11870
  - path: "endfieldmodcontroller/api.py"
    line: 9883
    end_line: 16864
apis:
  - protocol: rpc
    path: "read_launch_log"
    description:
      zh: >
          读启动日志尾部，给日志浮层显示。
          
      en: >
          Read the tail of the launch log for the log overlay.
          
  - protocol: rpc
    path: "export_diagnostics"
    description:
      zh: >
          导出诊断包（一次抓全，不用来回好几轮）。
          
      en: >
          Export a diagnostic bundle (one shot, everything needed to answer).
          
  - protocol: rpc
    path: "log_frontend_error"
    description:
      zh: >
          接住前端报错的入口，让界面崩了也能在日志里看到。
          
      en: >
          Sink for frontend errors, so a UI crash is still visible in the log.
          
  - protocol: rpc
    path: "clear_all_logs"
    description:
      zh: >
          清空日志（界面上会先让用户确认）。
          
      en: >
          Clear the logs (with the user's confirmation in the UI).
          
deps:
  - kind: call
    to: modecontroller.backend.observe
    label: {zh: "打诊断包", en: "Builds bundles"}
---
