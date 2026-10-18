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
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.960Z"
fingerprint: d90ec9f08a275ba753a633feb50e619a6904ff7569452c1e50b922d126aeaf9f
source:
  - path: "tests/test_dependencies.py"
    line: 2
    end_line: 91
  - path: "tests/test_runtime_deps.py"
    line: 2
    end_line: 172
  - path: "tests/test_selfupdate_stale.py"
    line: 2
    end_line: 132
  - path: "tests/test_asset_fetch_fallback.py"
    line: 2
    end_line: 96
apis: []
---
