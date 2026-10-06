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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.980Z"
fingerprint: cb23d790ce31aee351cd469bef261b461caeafb3b658a3c8df1c6ab9c0fc86f8
source:
  - path: "endfieldmodcontroller/integrity.py"
    line: 1
    end_line: 460
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
