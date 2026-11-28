---
uid: b1c0b001
id: modecontroller.backend.shell
parent: modecontroller.backend
tags: [entry, shell]
name: {zh: "外壳与入口", en: "App Shell & Entry"}
description:
  zh: >
      进程入口与 pywebview 外壳：单实例互斥、_MEI 临时目录残留清理、尽早创建窗口（先给不依赖后端的静态加载页）、绑定 js_api、起 webview 消息循环；另有 --cli 无界面入口供脚本冒烟测试。
      
  en: >
      Process entry points and the pywebview shell: one-instance guard, stale _MEI temp-dir cleanup, window creation with an early static loading screen, bind js_api, run the webview loop; plus the --cli entry for headless smoke tests.
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.796Z"
fingerprint: 348ac1ae7d9d0e51dd4ecc9298350391b2b4816a9f323f6027790c9e715be5e9
source:
  - path: "endfieldmodcontroller/app.py"
  - path: "endfieldmodcontroller/__main__.py"
  - path: "endfieldmodcontroller/cli.py"
deps:
  - kind: call
    to: modecontroller.backend.api
    label: {zh: "构造 js_api 对象", en: "Builds the js_api object"}
---
