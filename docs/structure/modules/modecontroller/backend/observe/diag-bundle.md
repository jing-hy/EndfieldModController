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
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.750Z"
fingerprint: c99fabfabd18ca7547b5f7ce6c4541782472e1509413a1fae1dd9f4046f42ed3
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 4575
    end_line: 10250
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5578
    end_line: 10316
apis:
  - protocol: rpc
    path: "create_diagnostic_bundle"
    description:
      zh: >
          打诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链、shader 清单、Windows 事件。
          
      en: >
          Build the diagnostic bundle: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection chain, shaders, Windows events.
          
---
