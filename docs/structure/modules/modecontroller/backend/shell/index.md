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
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.432Z"
fingerprint: 1d799ceae0d33c55c5bb676959b76e269bd71d3e837dda3166e7502c2421c29e
source:
  - path: "endfieldmodcontroller/app.py"
  - path: "endfieldmodcontroller/__main__.py"
  - path: "endfieldmodcontroller/cli.py"
deps:
  - kind: call
    to: modecontroller.backend.api
    label: {zh: "构造 js_api 对象", en: "Builds the js_api object"}
---
