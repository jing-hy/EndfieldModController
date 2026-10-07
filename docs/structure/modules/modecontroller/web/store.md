---
uid: 5f0a0005
id: modecontroller.web.store
parent: modecontroller.web
tags: [store, ui, lazy-load]
name: {zh: "商城页", en: "Store Page"}
description:
  zh: >
      商城主界面：左侧分类栏（根分类 + 中文角色名）＋右侧卡片网格，顶部一行工具条（短搜索框、排序、R18 三档、扫描与一键更新）。封面 16:9；图片只加载视口内、先出小图再换清晰图；详情在页内展开而不弹窗；点下载只入队不跳转。
      
  en: >
      Store UI: category rail plus card grid, one compact toolbar, 16:9 covers, viewport-only image loading, in-page detail, and enqueue-instead-of-navigate downloads.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:31:07.161Z"
fingerprint: d0030a50df4fdef59b2bfcfb91928e5f7430a5da6e632a88bcffe5243bf4bd6a
source:
  - path: "frontend/src/pages/StorePage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
