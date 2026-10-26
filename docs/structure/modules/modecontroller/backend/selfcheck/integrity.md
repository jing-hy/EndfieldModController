---
uid: b1d0e007
id: modecontroller.backend.selfcheck.integrity
parent: modecontroller.backend.selfcheck
tags: [repair]
name: {zh: "完整性修复入口", en: "Integrity Repair Entry"}
description:
  zh: >
      修复的总入口：跑完整条检查链，然后回报哪些已自动修好、哪些需要用户决定、哪些还坏着 —— 修复按钮与诊断摘要读的都是它。
      
  en: >
      The repair front door: run the whole check chain, then report what was fixed, what still needs the user and what remains broken — the payload the repair button and the diagnostic summary both read.
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.222Z"
fingerprint: bad4942ef9092edda4d87cd1eb5458843538b32488577a6c2006f074f492e7f1
source:
  - path: "endfieldmodcontroller/integrity.py"
    line: 2
    end_line: 1024
apis:
  - protocol: rpc
    path: "integrity.repair_integrity"
    description:
      zh: >
          修复总入口：跑完整条链，回报哪些已自动修好、哪些需用户决定、哪些还坏着。
          
      en: >
          The repair front door: run the whole chain, report what was fixed / still needs the user / remains broken.
          
deps:
  - kind: call
    to: modecontroller.backend.selfcheck.core
    label: {zh: "跑全部检查", en: "Runs every check"}
---
