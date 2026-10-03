---
uid: b1d0f00b
id: modecontroller.backend.observe.device
parent: modecontroller.backend.observe
tags: [device]
name: {zh: "设备事实", en: "Device Facts"}
description:
  zh: >
      从注册表读机器自身的事实：CPU 与内存、每块显示适配器及其驱动版本与显存、系统版本，以及“这一代显卡能不能跑 DLSS5”的结论 —— 界面与自检都用它。
      
  en: >
      Read the machine's own facts from the registry: CPU and memory, every display adapter with driver version and VRAM, OS build, and the verdict on whether this GPU generation can run DLSS5 — used both by the UI and by self-checks.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.314Z"
fingerprint: 109911a981598132125a16f7bea2d18c258b1403af92a4b758f02bb7ad83787a
source:
  - path: "endfieldmodcontroller/deviceinfo.py"
    line: 115
    end_line: 232
  - path: "endfieldmodcontroller/deviceinfo.py"
    line: 236
    end_line: 299
apis:
  - protocol: rpc
    path: "collect"
    description:
      zh: >
          从注册表读 CPU / 内存 / 每块显示适配器及驱动与显存 / 系统版本。
          
      en: >
          Read CPU / memory / every display adapter with driver and VRAM / OS build from the registry.
          
  - protocol: rpc
    path: "dlss5_supported"
    description:
      zh: >
          这一代显卡能不能跑 DLSS5 —— **迁移、开关闸门、自检三处共用这一处判据**。
          
      en: >
          Can this GPU generation run DLSS5 — the single predicate used by migration, the toggle gate and self-checks alike.
          
  - protocol: rpc
    path: "as_text"
    description:
      zh: >
          给诊断包用的人读设备摘要。
          
      en: >
          Human-readable device summary for the diagnostic bundle.
          
---
