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
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.285Z"
fingerprint: b608d714954cccb4fdfb4672631cffc3eb6a1ee2481e5e94eaa3690d8b43b2be
source:
  - path: "endfieldmodcontroller/app.py"
  - path: "endfieldmodcontroller/__main__.py"
  - path: "endfieldmodcontroller/cli.py"
deps:
  - kind: call
    to: modecontroller.backend.api
    label: {zh: "构造 js_api 对象", en: "Builds the js_api object"}
---
