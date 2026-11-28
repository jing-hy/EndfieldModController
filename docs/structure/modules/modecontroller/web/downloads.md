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
      
revision: c5e7502f33b821a8fbb9f32403d00f1d3540841b
updated_at: "2026-11-28T10:16:58.152Z"
fingerprint: 92e10d9dba3541cea3acd44450a7c91547e500f23ea08476e16d2f3dff104639
source:
  - path: "frontend/src/pages/DownloadsPage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
