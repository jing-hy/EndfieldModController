---
uid: b1d14011
id: modecontroller.scripts.setup-reshade
parent: modecontroller.scripts
tags: [dev]
name: {zh: "开发用 ReShade 安装", en: "Setup ReShade (dev)"}
description:
  zh: >
      在开发检出里把 ReShade 装好，方便本地调试 —— 让开发机与“用户机器被控制器部署完”的状态长得一样。
      
  en: >
      Set up ReShade in the development checkout for local debugging, so the developer machine mirrors what a user's machine looks like after the controller has deployed it.
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.830Z"
fingerprint: cb180272d278b4edf7a8bd6bb5730c7de77d945e0583d8cae57267ef0cd83f76
source:
  - path: "scripts/setup_reshade.py"
    line: 2
    end_line: 22
apis:
  - protocol: rpc
    path: "scripts.setup_reshade"
    description:
      zh: >
          在开发检出里把 ReShade 装好，让开发机与“用户机器部署完”的状态一致。
          
      en: >
          Set up ReShade in the development checkout so the dev machine mirrors a user's after deployment.
          
---
