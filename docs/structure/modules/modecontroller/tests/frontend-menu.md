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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.933Z"
fingerprint: 8872126dfca7e53ef495fefad6e1a57f95d6c7e0cc575a89989051ec4c8c9257
source:
  - path: "tests/test_frontend_menu_actions.py"
    line: 227
    end_line: 532
apis: []
---
