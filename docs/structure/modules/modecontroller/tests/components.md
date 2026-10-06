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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.997Z"
fingerprint: 2c0b6bd81729d6007ec100f00970d107865bda12e7535e7c114c01aa2afbcb6f
source:
  - path: "tests/test_dependencies.py"
    line: 1
    end_line: 89
  - path: "tests/test_runtime_deps.py"
    line: 1
    end_line: 144
  - path: "tests/test_selfupdate_stale.py"
    line: 1
    end_line: 130
  - path: "tests/test_asset_fetch_fallback.py"
    line: 1
    end_line: 94
apis: []
---
