---
uid: b1c0b006
id: modecontroller.backend.selfcheck
parent: modecontroller.backend
tags: [selfcheck]
name: {zh: "自检与完整性", en: "Self-Check & Integrity"}
description:
  zh: >
      启动自检与自愈：约 28 项检查，每项都验一个事实，能安全修的自动修（按库里的原件重建被旧版改坏的中转、按基线重展开随包组件、重写 XXMI 配置），修不了的如实回报；「修复」入口复用同一条链路，保证两个按钮行为一致。
      
  en: >
      Startup self-check and self-healing: ~28 checks that each verify a fact, fix what can be fixed safely (restage broken staging, restore bundled files from baseline, rewrite the XXMI config) and report what cannot; the repair entry point reuses exactly the same chain so both buttons behave alike.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.979Z"
fingerprint: 8f1ff1d5cc201fbb871fe7976b1bd66c72ecf30cbb96912f5453ca1cbd59c3cd
source:
  - path: "endfieldmodcontroller/initialize.py"
  - path: "endfieldmodcontroller/integrity.py"
deps:
  - kind: call
    to: modecontroller.backend.activation
    label: {zh: "修复时重做中转", en: "Restages when repairing"}
  - kind: call
    to: modecontroller.backend.launch
    label: {zh: "维护注入库", en: "Maintains injections"}
---
