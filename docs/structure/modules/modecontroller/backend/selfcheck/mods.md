---
uid: b1d0e004
id: modecontroller.backend.selfcheck.mods
parent: modecontroller.backend.selfcheck
tags: [mods]
name: {zh: "Mod 与中转检查", en: "Mod & Staging Checks"}
description:
  zh: >
      Mod 侧的检查：选中的 Mod 到底中转没有、中转树里有没有被旧版本删过 shader 汇编 endif 的破损文件、中转的 Mod 是否互相覆盖资源、控制器产物与面板数据在不在且一致。
      
  en: >
      The mod-side checks: are the selected mods actually staged, is anything in the staging tree damaged (older versions deleted shader-assembly endif), do staged mods overwrite each other's resources, is the controller mod and its panel data present and consistent.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.430Z"
fingerprint: 334016859c4b0b377474eb3c4dfa8e8207cba1c9329986788d8f207687218859
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 4873
    end_line: 8338
  - path: "endfieldmodcontroller/initialize.py"
    line: 5067
    end_line: 8511
  - path: "endfieldmodcontroller/initialize.py"
    line: 5144
    end_line: 8544
apis:
  - protocol: rpc
    path: "staging"
    description:
      zh: >
          自检项 key：选中的 Mod 是否真的已中转。
          
      en: >
          Self-check key: the selected mods are actually staged.
          
  - protocol: rpc
    path: "mod_conflicts"
    description:
      zh: >
          自检项 key：中转的 Mod 是否互相覆盖资源（已应用“跑通过就不再报”的过滤）。
          
      en: >
          Self-check key: staged mods do not overwrite each other's resources (with the proven-combination filter applied).
          
  - protocol: rpc
    path: "controller"
    description:
      zh: >
          自检项 key：控制器产物与面板数据在不在、一致不一致。
          
      en: >
          Self-check key: the controller mod and its panel data are present and consistent.
          
deps:
  - kind: call
    to: modecontroller.backend.activation.stage
    label: {zh: "重建中转", en: "Rebuilds staging"}
  - kind: call
    to: modecontroller.backend.library.controller
    label: {zh: "用冲突判据", en: "Uses conflict rule"}
---
