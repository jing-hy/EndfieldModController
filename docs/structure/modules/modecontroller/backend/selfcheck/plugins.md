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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.351Z"
fingerprint: 92e1ba767e4a78843f0e6b41af6090c4b897d224ae366014d5eb53aa5ef93d83
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 3921
    end_line: 6340
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
