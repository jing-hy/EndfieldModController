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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.969Z"
fingerprint: 1c07eedd6a7fe5dfb43dc3181e89a23a19b29ad13dfa3ef5e03e7c0f19549ca2
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 249
    end_line: 400
  - path: "endfieldmodcontroller/launcher.py"
    line: 1088
    end_line: 3032
  - path: "endfieldmodcontroller/launcher.py"
    line: 1945
    end_line: 3920
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
