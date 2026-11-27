---
uid: b1d13004
id: modecontroller.web.bridge
parent: modecontroller.web
tags: [bridge]
name: {zh: "后端桥接", en: "Backend Bridge"}
description:
  zh: >
      pywebview 桥接层（Vue 侧唯一入口）：call / waitForBridge / bridgeReady 与前端错误上报；调用失败仍是「弹窗 + 原样抛出」。
      
  en: >
      The single pywebview bridge for the Vue frontend: call/waitForBridge/bridgeReady plus frontend error reporting.
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.298Z"
fingerprint: 251bd7e907a4dabcd43892f3af99c11560aee1dc0769e6144e74bd06552c8c0c
source:
  - path: "frontend/src/lib/bridge.js"
    line: 2
    end_line: 110
apis:
  - protocol: rpc
    path: "web.call"
    description:
      zh: >
          通往后端的唯一门：一个会把失败报出来、而不是吞掉的包装。
          
      en: >
          The only door to the backend: a wrapper that reports failures instead of swallowing them.
          
  - protocol: rpc
    path: "web.showTab"
    description:
      zh: >
          切换页签，并记住选的是哪个。
          
      en: >
          Switch tabs, remembering the choice.
          
  - protocol: rpc
    path: "web.saveSelection"
    description:
      zh: >
          把当前勾选回写给后端。
          
      en: >
          Push the current selection back to the backend.
          
deps:
  - kind: call
    to: modecontroller.backend.api.state
    label: {zh: "调 js_api", en: "Invokes js_api"}
---
