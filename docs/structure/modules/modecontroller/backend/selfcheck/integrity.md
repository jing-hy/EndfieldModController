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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.889Z"
fingerprint: 3fa0cebe564cd102acd8cbc86222e697736ba44a3576773ec98e34b18867e3a2
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
