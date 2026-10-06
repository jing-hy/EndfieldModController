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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:01.011Z"
fingerprint: 147d369b229579e4bad482ff153c9e7b9ce9f53ee2b18391728d882a26d02594
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1472
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
