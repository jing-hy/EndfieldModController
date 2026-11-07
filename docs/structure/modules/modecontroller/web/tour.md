---
uid: b1d1300d
id: modecontroller.web.tour
parent: modecontroller.web
tags: [tour]
name: {zh: "新手引导", en: "First-Run Tour"}
description:
  zh: >
      首次启动引导（Vue）：判据取后端的 first_run + onboarding_done，只提示一次；提供「去依赖页 / 跳过」。
      
  en: >
      First-run onboarding (Vue): gated on the backend's first_run + onboarding_done so it only ever shows once.
      
revision: 89ad502e368be7ee5b8c45c1a4d735e1870f43b9
updated_at: "2026-11-07T04:43:41.711Z"
fingerprint: 6c538c2a63c3c16b36c78bcac0c3c8bb36658166c001a1eba81392af6055dee0
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1880
apis:
  - protocol: rpc
    path: "web.TOUR_STEPS"
    description:
      zh: >
          四步首跑引导：依赖页 → Mod 库 → 启动页 → 一键还原。
          
      en: >
          The four-step first-run tour: dependencies → library → launch → restore.
          
  - protocol: rpc
    path: "web.tourShow"
    description:
      zh: >
          显示一步：切页、等两帧、再测量并高亮目标控件。
          
      en: >
          Show one step: switch tab, wait two frames, then measure and highlight the target.
          
  - protocol: rpc
    path: "web.initTour"
    description:
      zh: >
          问一次要不要看引导；“跳过”也会被记住。
          
      en: >
          Ask once whether to take the tour; "skip" is remembered too.
          
---
