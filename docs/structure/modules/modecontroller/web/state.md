---
uid: b1d13001
id: modecontroller.web.state
parent: modecontroller.web
tags: [ui]
name: {zh: "状态与小工具", en: "UI State & Helpers"}
description:
  zh: >
      前端全局状态（Vue reactive）：get_state 结果、当前页签（支持 hash 深链与 last_tab）、主题读写。
      
  en: >
      Frontend global state: get_state payload, current tab (hash deep-link + last_tab), theme persistence.
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.119Z"
fingerprint: 40ea9ff156c58bc448e00084947bf68c48a34fb46b8fd991aa535cfdd2b1cf08
source:
  - path: "frontend/src/store.js"
    line: 2
    end_line: 401
apis:
  - protocol: rpc
    path: "web.escapeHtml"
    description:
      zh: >
          在拼进 innerHTML 之前转义不可信文本（Mod 名、分组、id、路径）。
          
      en: >
          Escape untrusted text before it reaches innerHTML (mod names, groups, ids, paths).
          
  - protocol: rpc
    path: "web.$"
    description:
      zh: >
          全脚本都在用的 `getElementById` 简写。
          
      en: >
          The tiny getElementById shorthand the whole script uses.
          
  - protocol: rpc
    path: "web.sanitizeSelection"
    description:
      zh: >
          启动前把已经不在的选中 id 剔掉。
          
      en: >
          Drop selection ids that no longer exist before a launch.
          
---
