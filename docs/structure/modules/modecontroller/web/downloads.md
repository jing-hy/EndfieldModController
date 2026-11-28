---
uid: 5f0a0006
id: modecontroller.web.downloads
parent: modecontroller.web
tags: [download, ui]
name: {zh: "下载页", en: "Downloads Page"}
description:
  zh: >
      下载中心界面：统一的 Mod 与组件任务列表、暂停/继续/取消/清空、组件任务的进度与日志框。承接从启动页、商城、依赖页发出的下载动作。
      
  en: >
      Download centre UI: a unified task list for mods and components with pause/resume/cancel/clear, plus progress and log box for component tasks.
      
revision: b124e58720a8b882c922f28505d3d1412c494693
updated_at: "2026-11-28T17:22:47.855Z"
fingerprint: 31eedf8a27c8336c901b000133282d5dee517cbc11ae5c8d56bfb76d032154b1
source:
  - path: "frontend/src/pages/DownloadsPage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
