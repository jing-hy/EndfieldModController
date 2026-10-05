---
uid: b1d11008
id: modecontroller.backend.components.github
parent: modecontroller.backend.components
tags: [github]
name: {zh: "GitHub 访问", en: "GitHub Access"}
description:
  zh: >
      不被限流也不被墙地访问 GitHub：token 解析、带缓存的 api_get、最新提交探测、release 查询（API 不通时回退到网页解析 —— 这个网络环境下很常见），以及按版本排资产。
      
  en: >
      Talk to GitHub without getting rate-limited or blocked: token resolution, a cached api_get, latest-commit probing, release lookup with a web-page fallback when the API is unreachable (common on this network), and asset sorting by version.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.300Z"
fingerprint: bfcb825b881a4b04679b89fecf86391b243f78eb48972dabee55af9ba782bd8c
source:
  - path: "endfieldmodcontroller/github.py"
    line: 41
    end_line: 209
  - path: "endfieldmodcontroller/github.py"
    line: 167
    end_line: 300
  - path: "endfieldmodcontroller/github.py"
    line: 256
    end_line: 468
apis:
  - protocol: rpc
    path: "api_get"
    description:
      zh: >
          带缓存的 GitHub API GET（避免被限流），并为本机网络保留网页解析回退。
          
      en: >
          Cached GitHub API GET (so we never get rate-limited), with a web-page fallback for this network.
          
  - protocol: rpc
    path: "releases_latest"
    description:
      zh: >
          查最新 Release（**设计上取不到预发布**）。
          
      en: >
          Latest release lookup (misses pre-releases by design).
          
  - protocol: rpc
    path: "releases_list"
    description:
      zh: >
          列出 Release（含预发布）—— 那些**只发预发布**的组件只能靠它拿到。
          
      en: >
          List releases including pre-releases — the only way to reach components published as pre-release only.
          
---
