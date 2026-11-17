---
uid: b1d0e501
id: modecontroller.backend.shell.ui-automation
parent: modecontroller.backend.shell
tags: [api, automation, accessibility]
name: {zh: "界面自动化通道", en: "UI Automation Channel"}
description:
  zh: >
      本机 HTTP 接口：把「点界面 / 开关 / 滑块 / 滚动」排成命令，交给前端在真实 DOM 上执行，再把结果回传。只绑 127.0.0.1，带启动时随机生成的 token；端口与 token 落在 runtime/_state/ui_api.json 供命令行客户端读取。
      
  en: >
      Local HTTP channel that queues UI commands (click / toggle / set value / scroll), has the frontend run them on the real DOM, and returns the result. Binds 127.0.0.1 only, guarded by a per-launch token; port and token live in runtime/_state/ui_api.json for the CLI client.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.114Z"
fingerprint: ffb39003ccfeee17cf76ee9e2b3421de9b7d0332781d1bc32e3eb388c62a7b1a
source:
  - path: "endfieldmodcontroller/ui_automation.py"
    line: 1
    end_line: 278
apis:
  - protocol: http
    method: GET
    path: "/health"
    description:
      zh: >
          探活（无需 token）。
          
      en: >
          Liveness probe (no token).
          
  - protocol: http
    method: GET
    path: "/state"
    description:
      zh: >
          界面快照：当前页面 + 可见可交互元素。
          
      en: >
          UI snapshot: current tab and visible interactive elements.
          
  - protocol: http
    method: POST
    path: "/act"
    description:
      zh: >
          执行界面动作：click / set / value / type / scroll / scroll-by / focus。
          
      en: >
          Run a UI action: click / set / value / type / scroll / scroll-by / focus.
          
deps:
  - kind: reference
    to: modecontroller.backend.api.mods
    label: {zh: "前端轮询桥", en: "Frontend poll bridge"}
---
