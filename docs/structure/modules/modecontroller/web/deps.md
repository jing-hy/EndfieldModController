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
      
revision: 0f41bf214f75c051e693ed36eb4bd6478655242e
updated_at: "2026-10-16T14:11:18.090Z"
fingerprint: c87cf6fa247e3ef28c213c5b3d5a21c59d51621b13e2c13c0132af5106714c7a
source:
  - path: "frontend/src/pages/DepsPage.vue"
    line: 2
    end_line: 1480
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
