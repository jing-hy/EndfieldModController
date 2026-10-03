---
uid: b1d13008
id: modecontroller.web.deps
parent: modecontroller.web
tags: [deps]
name: {zh: "依赖页", en: "Dependency Page"}
description:
  zh: >
      依赖页（Vue）：组件状态列表（读 dependency_report.manifest）、进度条与日志轮询、一键安装/更新。
      
  en: >
      Dependencies page (Vue): component list from dependency_report.manifest with progress polling and one-click update.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.332Z"
fingerprint: fff3d4b86a1aec0b9c4a847349d811b34e768d039bf477953727e8ec8adddb62
source:
  - path: "frontend/src/pages/DepsPage.vue"
    line: 1
    end_line: 1256
apis:
  - protocol: rpc
    path: "web.renderDependencies"
    description:
      zh: >
          渲染已装 / 缺失 / 可更新，并把程序自己置顶。
          
      en: >
          Render what is installed / missing / updatable, with the app itself pinned on top.
          
  - protocol: rpc
    path: "web.startFullUpdate"
    description:
      zh: >
          发起批量并逐行轮询进度（**分母固定、不到最后一刻不显示 100%**）。
          
      en: >
          Kick off the batch and poll its progress line by line (fixed denominator, never reaching 100% early).
          
  - protocol: rpc
    path: "web.pollDependencyProgress"
    description:
      zh: >
          轮询后端的依赖任务直到它结束。
          
      en: >
          Poll the backend's dependency task until it settles.
          
deps:
  - kind: call
    to: modecontroller.backend.api.deps
    label: {zh: "驱动组件更新", en: "Drives component update"}
---
