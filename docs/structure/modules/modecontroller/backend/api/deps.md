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
      
revision: bf4fd078330843729d79451ed7aa1a080a39340a
updated_at: "2026-11-07T06:45:10.107Z"
fingerprint: a2aceb007307b3128fb704cbe6421bec17f14f6c4dbe8fd425dabb33f26f857d
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2972
    end_line: 7053
  - path: "endfieldmodcontroller/api.py"
    line: 3178
    end_line: 10923
  - path: "endfieldmodcontroller/api.py"
    line: 9244
    end_line: 15916
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
