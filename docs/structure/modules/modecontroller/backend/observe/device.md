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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.975Z"
fingerprint: b2dd63c4ffab7ed942a515b3bd484ddf69a96fe439550e2669b3d0a4b7e56d57
source:
  - path: "endfieldmodcontroller/deviceinfo.py"
    line: 115
    end_line: 622
  - path: "endfieldmodcontroller/deviceinfo.py"
    line: 431
    end_line: 689
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
