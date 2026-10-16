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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.068Z"
fingerprint: b16d57e8199454d41e522994944848c2963e142d5c00b918a2e9231b09e77b82
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
