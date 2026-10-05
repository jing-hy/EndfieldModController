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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.317Z"
fingerprint: 8953c1b3674a022affaae19dfd2f51d6c489739683a202ea2fe9f74e71323ca1
source:
  - path: "endfieldmodcontroller/integrity.py"
    line: 1
    end_line: 386
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
