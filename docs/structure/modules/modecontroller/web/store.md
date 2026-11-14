---
uid: 5f0a0005
id: modecontroller.web.store
parent: modecontroller.web
tags: [store, ui, lazy-load]
name: {zh: "商城页", en: "Store Page"}
description:
  zh: >
      商城主界面：左侧分类栏（根分类 + 中文角色名）＋右侧卡片网格，顶部一行工具条（短搜索框、排序、R18 三档、扫描与一键更新）。分类/角色数字与右上角总数都取列表返回的那份索引计数，标签上的数 == 点进去的条数；打开商城页先增量刷新最上面，停留时每 60 秒继续；状态行显示索引条数、多久以前更新、是否不完整，并给「刷新索引」入口（索引建完会自动重载列表）。封面 16:9；图片只加载视口内；详情在页内展开而不弹窗；点下载只入队不跳转。
      
  en: >
      Store UI: category rail plus card grid, one compact toolbar. Category/character numbers and the header total come from the same index-derived counts returned by the list endpoint; on open the top of the index is refreshed incrementally and every 60s while staying; the status line shows index size, age and completeness with a refresh-index entry (the list reloads when a build finishes). 16:9 covers, viewport-only images, in-page detail, enqueue-instead-of-navigate downloads.
      
revision: 5ad99916cdff1745b2f88ff3fa46f4116ff95157
updated_at: "2026-11-14T05:47:42.779Z"
fingerprint: 7e1c40e22c478697c4a0d6ecbf63ea29782a3b598b91fc11b65049a49b0bcd64
source:
  - path: "frontend/src/pages/StorePage.vue"
apis: []
deps:
  - kind: call
    to: modecontroller.web.bridge
    label: {zh: "经桥调用后端接口", en: "Call backend via bridge"}
---
