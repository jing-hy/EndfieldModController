---
uid: b1d0e502
id: modecontroller.web.ui-automation
parent: modecontroller.web
tags: [web, automation, accessibility]
name: {zh: "界面自动化（前端）", en: "UI Automation (frontend)"}
description:
  zh: >
      无障碍通道的前端那一半：生成可交互元素快照（带可直接使用的 CSS 选择器），并在真实 DOM 上执行点击 / 赋开关 / 赋值 / 滚动；每 300ms 向后端取一次命令。异常一律吞掉，坏掉不能拖累界面。
      
  en: >
      Frontend half of the accessibility channel: snapshots interactive elements (with usable CSS selectors) and performs click / toggle / set value / scroll on the real DOM, polling the backend every 300ms. All errors are swallowed so a broken channel cannot hurt the UI.
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.787Z"
fingerprint: 146f8b09822b8e4e9d681a5987818599c7d93aa25fac5d9cbc66db36742daed7
source:
  - path: "frontend/src/lib/uiAutomation.js"
    line: 302
    end_line: 898
apis:
  - protocol: rpc
    path: "window.__mcUi.snapshot"
    description:
      zh: >
          返回界面快照（页面 + 可交互元素）。
          
      en: >
          Return a UI snapshot (tab + interactive elements).
          
  - protocol: rpc
    path: "window.__mcUi.act"
    description:
      zh: >
          在真实 DOM 上执行一个动作。
          
      en: >
          Run one action on the real DOM.
          
deps:
  - kind: call
    to: modecontroller.backend.shell.ui-automation
    label: {zh: "轮询命令并回传结果", en: "Poll commands, post results"}
---
