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
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.410Z"
fingerprint: 7fe83653992baa51db09e9ab79d9e325122b81bdf89fad9b5d4c5d47f2b53ce5
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1622
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
