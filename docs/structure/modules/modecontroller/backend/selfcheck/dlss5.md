---
uid: b1d0e002
id: modecontroller.backend.selfcheck.dlss5
parent: modecontroller.backend.selfcheck
tags: [dlss5]
name: {zh: "DLSS5 检查", en: "DLSS5 Checks"}
description:
  zh: >
      DLSS5 出帧前要验的全部：dlss5 目录、shader 套装、preset（且不能砸掉 ReShade 自己写的激活状态）、显卡代次支持、NGX 是否被第三方截获、上次 NR 到底绑上没有、喂帧是否冗余，以及 NRStyle 只报不改的规矩。
      
  en: >
      Everything DLSS5 needs verified before it can show a frame: the dlss5 folder, the shader set, the preset (and not nuking ReShade's own activation flags), GPU generation support, third-party NGX interception, whether the NR path bound last run, feeder redundancy, and the NRStyle report-only rule.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.317Z"
fingerprint: 79ede51fc38bb72e15920536adcaba2411f2fbddeaff94ff12ac911b8e2eb95a
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 456
    end_line: 1243
  - path: "endfieldmodcontroller/initialize.py"
    line: 901
    end_line: 3961
  - path: "endfieldmodcontroller/initialize.py"
    line: 2949
    end_line: 4580
apis:
  - protocol: rpc
    path: "dlss5_dir"
    description:
      zh: >
          自检项 key：dlss5 目录与其中的组件是否就位。
          
      en: >
          Self-check key: the dlss5 folder and its payload are present.
          
  - protocol: rpc
    path: "dlss5_shaders"
    description:
      zh: >
          自检项 key：shader 套装（标准头 + DLSS5_Feed.fx + iMMERSE）是否齐。
          
      en: >
          Self-check key: the shader set (standard headers + DLSS5_Feed.fx + iMMERSE) is complete.
          
  - protocol: rpc
    path: "dlss5_preset"
    description:
      zh: >
          自检项 key：preset 是否两项都启用且顺序正确 —— 修它时**不能砸掉 ReShade 自己写的激活状态**。
          
      en: >
          Self-check key: the preset enables both techniques in the right order — and repairing it must not clobber ReShade's own flags.
          
  - protocol: rpc
    path: "dlss5_gpu_support"
    description:
      zh: >
          自检项 key：这一代显卡到底能不能跑 DLSS5（**永远 ok** —— 硬件支持范围不是用户的故障）。
          
      en: >
          Self-check key: this GPU generation can run DLSS5 at all (always ok — a hardware limit is not a user's fault).
          
deps:
  - kind: reference
    to: modecontroller.backend.observe
    label: {zh: "用设备事实", en: "Uses device facts"}
---
