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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.318Z"
fingerprint: 79ede51fc38bb72e15920536adcaba2411f2fbddeaff94ff12ac911b8e2eb95a
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 2657
    end_line: 3906
  - path: "endfieldmodcontroller/initialize.py"
    line: 2851
    end_line: 4079
  - path: "endfieldmodcontroller/initialize.py"
    line: 2928
    end_line: 4112
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
