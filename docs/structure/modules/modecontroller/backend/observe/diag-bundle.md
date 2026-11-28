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
      
revision: c5e7502f33b821a8fbb9f32403d00f1d3540841b
updated_at: "2026-11-28T10:16:58.120Z"
fingerprint: 78bdb7036548a0be5b84d4d56eb1fd5ab9c6c64a80601f22d74daa8500f15b1f
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 4530
    end_line: 10160
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 5533
    end_line: 10226
apis:
  - protocol: rpc
    path: "create_diagnostic_bundle"
    description:
      zh: >
          打诊断包：带哈希的运行时件清单、DLSS5 指纹、NGX 消费者摘要、XXMI 注入链、shader 清单、Windows 事件。
          
      en: >
          Build the diagnostic bundle: runtime inventory with hashes, DLSS5 fingerprint, NGX consumer summary, XXMI injection chain, shaders, Windows events.
          
---
