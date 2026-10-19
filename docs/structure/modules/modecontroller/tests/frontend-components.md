---
uid: b1d1ab04
id: modecontroller.tests.frontend-components
parent: modecontroller.tests
tags: [tests, web]
name: {zh: "前端组件导入测试", en: "Front-end Component Import Tests"}
description:
  zh: >
      静态检查：模板里用到的每个组件标签都必须 import。Vue 对未解析的标签**静默跳过**（页面上什么都不渲染，而 ref 拿到的是 DOM 元素而不是组件实例，调方法直接 `openFor is not a function`）—— 正是「更改角色归属点了没反应」的真因（服装页那个归类弹窗从来没 import，辅助页有）。顺带抓出同一页 `<Badge>` 也漏了 import。
      
  en: >
      Static check that every component tag used in a template is actually imported. Vue silently treats an unresolved tag as a custom element: nothing renders, and a template ref hands back a DOM element instead of the component instance (calling its methods throws `openFor is not a function`) — which is exactly the "change character assignment does nothing" bug.
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.892Z"
fingerprint: af758654b734734c384ad167937082b353df6140563c2ee45c7fc3adb27a321b
source:
  - path: "tests/test_frontend_components.py"
    line: 338
    end_line: 784
apis: []
---
