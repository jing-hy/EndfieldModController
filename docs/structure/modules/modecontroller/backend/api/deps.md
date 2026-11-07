---
uid: b1d0c004
id: modecontroller.backend.api.deps
parent: modecontroller.backend.api
tags: [api, deps]
name: {zh: "依赖与组件", en: "Dependencies & Components"}
description:
  zh: >
      依赖页的后端：状态报告、带进度轮询的批量安装/更新、逐组件版本，以及 DLSS5 运行库与喂帧 addon 的专用安装入口。
      
  en: >
      The dependency page's backend: status report, batch install/update with progress polling, per-component versions, and the specialised installers for the DLSS5 runtime and the feeder add-on.
      
revision: f6f018e650111be669b39896b4a614a0d757c3a7
updated_at: "2026-11-07T04:47:38.249Z"
fingerprint: d4747ea6c02c00507de3113260fb95ed7a96c782001b24a0feb4fca2141804b4
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2923
    end_line: 6425
  - path: "endfieldmodcontroller/api.py"
    line: 3129
    end_line: 10295
  - path: "endfieldmodcontroller/api.py"
    line: 8930
    end_line: 15288
apis:
  - protocol: rpc
    path: "dependency_status"
    description:
      zh: >
          依赖页的数据：已装、缺失、可更新的都有哪些。
          
      en: >
          The dependency page's data: what is installed, what is missing, what can update.
          
  - protocol: rpc
    path: "start_full_update"
    description:
      zh: >
          后台批量安装/更新所有缺失或过期的组件。
          
      en: >
          Start a batch install/update of all missing or outdated components in the background.
          
  - protocol: rpc
    path: "get_dependency_progress"
    description:
      zh: >
          轮询正在跑的批处理进度（当前/总数/阶段文案）。
          
      en: >
          Poll the running batch's progress (current / total / stage lines).
          
  - protocol: rpc
    path: "component_versions"
    description:
      zh: >
          逐组件的版本报告（已装 vs 最新）。
          
      en: >
          Per-component version report (installed vs latest).
          
  - protocol: rpc
    path: "update_component"
    description:
      zh: >
          安装或更新指定的单个组件。
          
      en: >
          Install or update one named component.
          
deps:
  - kind: call
    to: modecontroller.backend.components
    label: {zh: "安装组件", en: "Installs components"}
---
