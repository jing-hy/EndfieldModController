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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.905Z"
fingerprint: 0e7871012c31c8dd07f93b75d8ec9f3923a4c1648c4a4bfbad45f027e51b1160
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
