---
uid: b1d13002
id: modecontroller.web.theme
parent: modecontroller.web
tags: [theme]
name: {zh: "主题配色", en: "Themes"}
description:
  zh: >
      设计令牌与主题（tokens.css）：浅色基底 + 去饱和强调色，6 套主题沿用原名；日志框在任意主题下都是纯黑可复制。
      
  en: >
      Design tokens and themes: light base with desaturated accent, six themes keeping their original names; the log box stays pure black and selectable.
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.098Z"
fingerprint: ef935d02a70fa5cddc8ad390cae1c79aa84136e50c2ffe12c3debabc8a96bb22
source:
  - path: "frontend/src/styles/tokens.css"
    line: 227
    end_line: 642
apis:
  - protocol: rpc
    path: "web.applyTheme"
    description:
      zh: >
          通过换根元素上的 class 应用主题，并记住它。
          
      en: >
          Apply one of the themes by swapping a class on the root element, and remember it.
          
  - protocol: rpc
    path: "web.THEMES"
    description:
      zh: >
          六个合法主题名 —— `<head>` 里的内联脚本必须与它一致，否则主题会被静默改掉。
          
      en: >
          The six allowed theme names — the inline head script must agree with this list, or a theme gets silently rewritten.
          
---
