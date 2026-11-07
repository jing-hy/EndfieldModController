---
uid: b1d1ab06
id: modecontroller.tests.frontend-tour
parent: modecontroller.tests
tags: [tests, web]
name: {zh: "新手引导落点测试", en: "Front-end Tour Anchor Tests"}
description:
  zh: >
      前端静态回归：新手引导每一步的高亮目标 id 必须在源码里真的存在（0.9.5 那条落点不存在的坑），并钉住第 2 步就是「Mod 商城」、正文讲清拖入 / 商城 / 粘贴网址三种添加方式。vite build 不会报这类错。
      
  en: >
      Static front-end regression: every tour step's highlight target id must actually exist in the sources (the 0.9.5 dangling-anchor bug), and step 2 must point at the Mod Store while its copy covers all three ways to add a mod. vite build cannot catch this.
      
revision: 89bc0c73458ae7cf701d5c51691a28cfbebc2135
updated_at: "2026-11-07T05:15:40.261Z"
fingerprint: b56464bf79de8a106ece941c2afe4dcdb78e2106f37c802d9daa53824135982f
source:
  - path: "tests/test_frontend_tour_targets.py"
    line: 86
apis: []
---
