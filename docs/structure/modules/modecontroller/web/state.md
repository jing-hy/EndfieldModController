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
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.413Z"
fingerprint: f9b091d3c8bd0ff57b8c55d1ce9c129cbad31e0052704a5e9b183b09b6f4ab34
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
