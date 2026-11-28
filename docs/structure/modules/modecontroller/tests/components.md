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
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.832Z"
fingerprint: f48cd84af10ce7040be083a9b590a18819bca17c44b938782d02316637c9bf83
source:
  - path: "tests/test_dependencies.py"
    line: 2
    end_line: 91
  - path: "tests/test_runtime_deps.py"
    line: 2
    end_line: 676
  - path: "tests/test_selfupdate_stale.py"
    line: 2
    end_line: 132
  - path: "tests/test_asset_fetch_fallback.py"
    line: 2
    end_line: 96
apis: []
---
