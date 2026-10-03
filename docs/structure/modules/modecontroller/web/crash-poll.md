---
uid: b1d1300f
id: modecontroller.web.crash-poll
parent: modecontroller.web
tags: [crash]
name: {zh: "崩溃轮询", en: "Crash Polling"}
description:
  zh: >
      前端错误上报（Vue）：window error / unhandledrejection 上报后端日志，便于界面空白时定位。
      
  en: >
      Frontend error reporting (Vue): window error and unhandledrejection are forwarded to the backend log.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.332Z"
fingerprint: 83cda12b0aed97e5a4b3f723099f81a11589e8437a4c6c57bc34854751bc5978
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 936
apis:
  - protocol: rpc
    path: "web.startCrashPolling"
    description:
      zh: >
          游戏跑着时每隔几秒问一次崩溃监视器，这趟跑砸了就把弹窗推出来。
          
      en: >
          Poll the crash watcher every few seconds while the game runs, and surface the modal when a run ended badly.
          
  - protocol: rpc
    path: "web.startCharacterCheck"
    description:
      zh: >
          问用户一个没认出来的 Mod 属于谁，并**预选**最优猜测。
          
      en: >
          Ask which character an unrecognised mod belongs to, pre-selecting the best guess.
          
---
