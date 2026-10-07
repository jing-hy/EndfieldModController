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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:31:07.162Z"
fingerprint: e4678713c987e0025cd03b94ad72ecf99b988da2491da3c07126cc2d3eb44466
source:
  - path: "frontend/src/pages/DownloadsPage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
