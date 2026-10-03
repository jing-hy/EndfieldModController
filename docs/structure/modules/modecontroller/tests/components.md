---
uid: b1d15006
id: modecontroller.tests.components
parent: modecontroller.tests
tags: [tests]
name: {zh: "下载与更新测试", en: "Fetch & Update Tests"}
description:
  zh: >
      下载/安装/更新的测试：依赖清单与安装器、内置组件、基线修复、资产拉取回退、多线下载的记账、程序自更新（含“残留载荷”那种情形），以及 API 不通时的网页回退。
      
  en: >
      Tests for fetching, installing and updating things: the dependency manifest and installer, built-in components, baseline repair, asset-fetch fallbacks, multi-line download bookkeeping, self-update including the stale-payload case, and the web fallback when the API is unreachable.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.326Z"
fingerprint: a3067fca02d909ae9fd77ce207b010cbbe2f1885e68350ddf5d33510c9cfa701
source:
  - path: "tests/test_dependencies.py"
    line: 1
    end_line: 89
  - path: "tests/test_runtime_deps.py"
    line: 1
    end_line: 134
  - path: "tests/test_selfupdate_stale.py"
    line: 1
    end_line: 110
  - path: "tests/test_asset_fetch_fallback.py"
    line: 1
    end_line: 94
apis: []
---
