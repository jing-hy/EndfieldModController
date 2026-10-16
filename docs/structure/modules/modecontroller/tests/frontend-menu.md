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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.064Z"
fingerprint: 5f0abf1c61238664a394927a59eeac7f86a314adc2e3e98a1c63f35f07952060
source:
  - path: "tests/test_frontend_menu_actions.py"
    line: 227
    end_line: 532
apis: []
---
