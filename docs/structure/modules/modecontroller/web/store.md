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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.363Z"
fingerprint: 7e3fd9a8db4f01a111ea3a31e709c3af0b4d378caa9cc84b83b96603e095f3e1
source:
  - path: "frontend/src/pages/StorePage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
