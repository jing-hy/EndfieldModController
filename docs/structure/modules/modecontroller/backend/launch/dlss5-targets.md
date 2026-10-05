---
uid: b1d0d004
id: modecontroller.backend.launch.dlss5-targets
parent: modecontroller.backend.launch
tags: [dlss5]
name: {zh: "DLSS5 注入目标", en: "DLSS5 Injection Targets"}
description:
  zh: >
      DLSS5 挂在哪里：枚举 d3d12 目标、配置注入、把 ReShade 运行时与 shader 搜索路径摆好，并把不需要的 addon 挪开。
      
  en: >
      Where DLSS5 gets hooked: enumerate candidate d3d12 targets, configure the injection, stage the ReShade runtime with the right environment and effect search paths, and keep unwanted add-ons out of the way.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.307Z"
fingerprint: 625d41711e2451a0f8a305d04dd8a75624112aefc037c331b8863d1d6749bd2d
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 249
    end_line: 358
  - path: "endfieldmodcontroller/launcher.py"
    line: 873
    end_line: 1917
  - path: "endfieldmodcontroller/launcher.py"
    line: 1497
    end_line: 2647
apis:
  - protocol: rpc
    path: "dlss5_injection_targets"
    description:
      zh: >
          这次部署里 DLSS5 能挂哪些 d3d12 目标（取决于找不找得到 EFMI 的 d3d11.dll）。
          
      en: >
          Which d3d12 targets DLSS5 can hook in this deployment (depends on the EFMI d3d11.dll being findable).
          
  - protocol: rpc
    path: "configure_dlss5_injection"
    description:
      zh: >
          一步配好 DLSS5 注入及其签名。
          
      en: >
          Configure the DLSS5 injection and its signing in one step.
          
  - protocol: rpc
    path: "prepare_reshade_runtime"
    description:
      zh: >
          把 ReShade 运行时、环境变量与 shader 搜索路径摆好。
          
      en: >
          Stage the ReShade runtime with the right environment and effect search paths.
          
---
