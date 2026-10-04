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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.294Z"
fingerprint: f4f737f3126ceb30b7fe4eb77e658a2d448e8b85926c1be3e9f378bba509a468
source:
  - path: "endfieldmodcontroller/api.py"
    line: 1495
    end_line: 1855
  - path: "endfieldmodcontroller/api.py"
    line: 1667
    end_line: 2720
  - path: "endfieldmodcontroller/api.py"
    line: 4708
    end_line: 6844
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
