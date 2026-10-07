---
uid: b1c0b007
id: modecontroller.backend.api
parent: modecontroller.backend
tags: [api, facade]
name: {zh: "接口层（js_api）", en: "js_api Facade"}
description:
  zh: >
      前端进入后端的唯一门：一个类上挂几十个 js_api 方法 —— Mod 库读写与导入、依赖清单与安装进度、一键启动与启动预览、设置与主题、自检与修复、崩溃包与诊断包、公告与预警。构造必须快，重活丢后台线程 + 进度轮询。
      
  en: >
      The only door the UI has into the backend: one class carrying dozens of js_api methods — mod-library read/import, dependency manifest and install progress, one-click launch and preview, settings and theme, self-check and repair, crash/diagnostic bundles, announcements and alerts. Construction must stay fast; heavy work goes to background threads with progress polling.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.222Z"
fingerprint: 0f608d60724207320bfff4f39b5fe520386e86f6e9fd3eab28611d3942a453de
source:
  - path: "endfieldmodcontroller/api.py"
---
