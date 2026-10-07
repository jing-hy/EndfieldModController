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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.351Z"
fingerprint: 92e1ba767e4a78843f0e6b41af6090c4b897d224ae366014d5eb53aa5ef93d83
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 3825
    end_line: 6242
  - path: "endfieldmodcontroller/initialize.py"
    line: 4019
    end_line: 6415
  - path: "endfieldmodcontroller/initialize.py"
    line: 4096
    end_line: 6448
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
