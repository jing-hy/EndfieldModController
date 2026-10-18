---
uid: b1d0e005
id: modecontroller.backend.selfcheck.plugins
parent: modecontroller.backend.selfcheck
tags: [plugins]
name: {zh: "子插件检查", en: "Sub-Plugin Checks"}
description:
  zh: >
      两个可选子插件的检查：Poser 是否真的部署好了（别因为安装记录看着“缺失”就每点一次修复重跑一遍向导）、乳摇物理是否已安装并注入。
      
  en: >
      Checks for the two optional sub-plugins: whether Poser is actually deployed (and not re-running its wizard on every repair because an install record looks missing) and whether jiggle physics is installed and injected.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.431Z"
fingerprint: 334016859c4b0b377474eb3c4dfa8e8207cba1c9329986788d8f207687218859
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 4969
    end_line: 8436
apis:
  - protocol: rpc
    path: "poser"
    description:
      zh: >
          自检项 key：摆姿插件是否真的部署好了（安装记录按 `utf-8-sig` 读，BOM 不会导致反复重装）。
          
      en: >
          Self-check key: the Poser plugin is really deployed (and its record is read as utf-8-sig so a BOM doesn't trigger endless reinstalls).
          
  - protocol: rpc
    path: "sbm"
    description:
      zh: >
          自检项 key：乳摇物理是否已安装并注入。
          
      en: >
          Self-check key: the jiggle-physics plugin is installed and injected.
          
deps:
  - kind: call
    to: modecontroller.backend.game
    label: {zh: "驱动 Poser 部署", en: "Drives Poser deploy"}
---
