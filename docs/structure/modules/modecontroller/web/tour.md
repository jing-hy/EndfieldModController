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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.364Z"
fingerprint: f4dc49f90907b364b943ecb9b1066d830e5c009758fac9f04eeb4623494a9ad0
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1620
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
