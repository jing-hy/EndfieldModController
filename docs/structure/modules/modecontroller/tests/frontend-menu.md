---
uid: b1d1ab03
id: modecontroller.tests.frontend-menu
parent: modecontroller.tests
tags: [tests, web]
name: {zh: "前端菜单动作测试", en: "Front-end Menu Action Tests"}
description:
  zh: >
      前端菜单动作的静态回归（用户反馈「Mod 的更多中点击更改角色归属无反应」）：模板里传的每个动作名都必须在处理函数里有对应分支；catch 不许静默吞错；卡片上的标签必须把自己那条 Mod 一起传进去。vite build 不会报这类错，所以单独钉住。
      
  en: >
      Static regression for the front-end menu actions (the "change character assignment does nothing" report): every action name the template passes must have a branch in the handler, the handler's catch must not swallow errors, and the card badge must pass its own mod.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.276Z"
fingerprint: b32cabf7c60bfa13a0df8a8010af8817b14fb45df1b0c996e90c0deb8b9f189a
source:
  - path: "tests/test_frontend_menu_actions.py"
    line: 226
    end_line: 530
apis: []
---
