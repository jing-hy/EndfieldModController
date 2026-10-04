---
uid: b1d0f008
id: modecontroller.backend.observe.diag-bundle
parent: modecontroller.backend.observe
tags: [diagnostics]
name: {zh: "诊断包", en: "Diagnostic Bundle"}
description:
  zh: >
      打反馈链路依赖的诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链摘要、shader 清单，以及一段 Windows 事件日志 —— 目标是“一轮就能答清楚”。
      
  en: >
      Build the diagnostic bundle the feedback flow depends on: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection-chain summary, shader list, plus a Windows event-log slice — sized to answer the question in one round.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.314Z"
fingerprint: 0c53c8639adc28a15a835bab7ab846058eb0edaca5528357bc84a1ba597a42dc
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 654
    end_line: 1048
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 977
    end_line: 1114
apis:
  - protocol: rpc
    path: "create_diagnostic_bundle"
    description:
      zh: >
          打诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链、shader 清单、Windows 事件。
          
      en: >
          Build the diagnostic bundle: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection chain, shaders, Windows events.
          
---
