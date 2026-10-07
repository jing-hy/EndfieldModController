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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.283Z"
fingerprint: df9c5be8364d65f284fec6de907008b1d43d07019626d75d370712a579af49da
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1606
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
