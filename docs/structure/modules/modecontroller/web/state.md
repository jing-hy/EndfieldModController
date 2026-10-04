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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.334Z"
fingerprint: 4b9e77ec8be8ff7a6b4575d086659d5fb87acb1ff52e136046acb6fa2b5a222f
source:
  - path: "frontend/src/store.js"
    line: 1
    end_line: 213
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
