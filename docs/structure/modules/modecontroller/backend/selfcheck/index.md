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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.889Z"
fingerprint: 070434e3c629766c22b656f4f8fa6b7ed681e465fc35e7c0333de23787f8659b
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
