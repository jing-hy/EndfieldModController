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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.255Z"
fingerprint: abfd0c804e9e9b060e686ccb47d676aa329b794e5ea1ee0147ebb8416411ac33
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
