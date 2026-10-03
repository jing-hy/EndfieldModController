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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.319Z"
fingerprint: 196f4242bab23a71fdf6bcb5698a6330588b0d96025cff8e817b507c3f8dfba2
source:
  - path: "endfieldmodcontroller/app.py"
  - path: "endfieldmodcontroller/__main__.py"
  - path: "endfieldmodcontroller/cli.py"
deps:
  - kind: call
    to: modecontroller.backend.api
    label: {zh: "构造 js_api 对象", en: "Builds the js_api object"}
---
