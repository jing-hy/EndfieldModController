---
uid: 5f0a0002
id: modecontroller.backend.store.catalog
parent: modecontroller.backend.store
tags: [gamebanana, catalog, thumbnail]
name: {zh: "香蕉网数据层", en: "GameBanana Catalog"}
description:
  zh: >
      GameBanana apiv11 的匿名访问层：列表、搜索、分类树、详情、缩略图与全量索引。三条实测约束决定实现：① 只有 Subfeed 认排序且每页固定 15；② Mod/Index 能翻大页但完全不支持排序；③ 图片 CDN 极慢，因此自带本地缓存并由进程内只读服务直出。索引与分类树都带字段版本号，口径变化会自动失效重建。
      
  en: >
      Anonymous access layer for the GameBanana apiv11 API: listings, search, category tree, details, thumbnails and the full index. Three measured constraints shape it, plus field-versioned caches.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.352Z"
fingerprint: d6509dd7f69252d1dd46fcc79dae52faf0a853eb68fc5b78ed38143063e2d9e2
source:
  - path: "endfieldmodcontroller/modstore.py"
apis:
  - protocol: http
    method: GET
    path: "/apiv11/Mod/Index"
    description:
      zh: >
          分页拉取 Mod 列表（不支持排序，每页上限 50）
          
      en: >
          Paged mod list (no sorting, max 50 per page)
          
  - protocol: http
    method: GET
    path: "/apiv11/Game/21842/Subfeed"
    description:
      zh: >
          按更新/发布排序的列表（每页固定 15）
          
      en: >
          Sorted listing (fixed 15 per page)
          
  - protocol: http
    method: GET
    path: "/apiv11/Util/Search/Results"
    description:
      zh: >
          按名称或作者搜索
          
      en: >
          Search by name or author
          
  - protocol: http
    method: GET
    path: "/apiv11/Mod/Categories"
    description:
      zh: >
          分类树（根分类 → 角色）
          
      en: >
          Category tree
          
  - protocol: http
    method: GET
    path: "/apiv11/Mod/{id}"
    description:
      zh: >
          单条详情（瘦查询字段白名单）
          
      en: >
          Single mod detail (slim whitelist)
          
  - protocol: file
    path: "runtime/cache/modstore/thumbs/{sha1}.jpg"
    description:
      zh: >
          图片本地缓存（原样落盘，另由本地只读服务直出）
          
      en: >
          Local image cache, served by the read-only server
          
deps:
  - kind: reference
    to: modecontroller.backend.config.fsutil
    label: {zh: "读写 JSON 缓存与原子落盘", en: "JSON caches, atomic writes"}
---
