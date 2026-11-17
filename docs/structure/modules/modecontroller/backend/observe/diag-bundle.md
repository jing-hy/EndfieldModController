---
uid: b1d0f008
id: modecontroller.backend.observe.diag-bundle
parent: modecontroller.backend.observe
tags: [diagnostics]
name: {zh: "诊断包", en: "Diagnostic Bundle"}
description:
  zh: >
      打反馈链路依赖的诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链摘要（含它的 importer 目录、以及两侧会不会注入同一个 loader）、shader 清单，以及一段 Windows 事件日志 —— 目标是“一轮就能答清楚”。
      
  en: >
      Build the diagnostic bundle the feedback flow depends on: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection-chain summary (including its importer folder and whether both sides would inject the same loader), shader list, plus a Windows event-log slice.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.103Z"
fingerprint: 145acec6558ee4c3e5d09f69f06b388891220bd57698d13a9c9af203d9574323
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 4394
    end_line: 9888
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5397
    end_line: 9954
apis:
  - protocol: rpc
    path: "create_diagnostic_bundle"
    description:
      zh: >
          打诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链、shader 清单、Windows 事件。
          
      en: >
          Build the diagnostic bundle: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection chain, shaders, Windows events.
          
---
