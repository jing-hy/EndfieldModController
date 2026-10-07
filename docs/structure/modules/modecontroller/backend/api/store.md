---
uid: 5f0a0004
id: modecontroller.backend.api.store
parent: modecontroller.backend.api
tags: [api, store, download]
name: {zh: "商城与下载中心接口", en: "Store & Download APIs"}
description:
  zh: >
      商城主流程与下载中心的 js_api 面：列表/分类/详情/备图/批量扫描与一键更新，以及下载任务的快照、暂停、继续、取消、清空。下载动作只入队不跳转；重活都在后台线程里做。
      
  en: >
      js_api surface for the store flow and the download centre: listing, categories, detail, image preparation, batch scan and update-all, plus task snapshot, pause, resume, cancel and clear. Enqueues instead of navigating.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.226Z"
fingerprint: 0f608d60724207320bfff4f39b5fe520386e86f6e9fd3eab28611d3942a453de
source:
  - path: "endfieldmodcontroller/api.py"
apis:
  - protocol: rpc
    path: "mod_store_list"
    description:
      zh: >
          商城列表（分页/分类/角色/排序/R18 三档）
          
      en: >
          Store listing with filters and R18 tri-state
          
  - protocol: rpc
    path: "mod_store_categories"
    description:
      zh: >
          分类树与角色名单（附中文名）
          
      en: >
          Category tree and characters (Chinese names)
          
  - protocol: rpc
    path: "mod_store_detail"
    description:
      zh: >
          详情（多图 + 更新记录 + 文件清单）
          
      en: >
          Detail with images, updates and files
          
  - protocol: rpc
    path: "mod_store_prepare_images"
    description:
      zh: >
          批量备图并返回本地服务 URL
          
      en: >
          Prepare images, return local URLs
          
  - protocol: rpc
    path: "mod_store_check_updates"
    description:
      zh: >
          批量扫描已安装 Mod 的更新
          
      en: >
          Batch-scan installed mods for updates
          
  - protocol: rpc
    path: "mod_store_update_all"
    description:
      zh: >
          把全部可更新项排进下载队列
          
      en: >
          Enqueue every available update
          
  - protocol: rpc
    path: "downloads_snapshot"
    description:
      zh: >
          下载任务快照（含组件任务）
          
      en: >
          Download task snapshot
          
  - protocol: rpc
    path: "downloads_pause"
    description:
      zh: >
          暂停任务
          
      en: >
          Pause a task
          
  - protocol: rpc
    path: "downloads_resume"
    description:
      zh: >
          继续任务
          
      en: >
          Resume a task
          
  - protocol: rpc
    path: "downloads_cancel"
    description:
      zh: >
          取消任务
          
      en: >
          Cancel a task
          
  - protocol: rpc
    path: "downloads_clear"
    description:
      zh: >
          清空任务（含待办队列）
          
      en: >
          Clear tasks including pending queue
          
deps:
  - kind: call
    to: modecontroller.backend.store.catalog
    label: {zh: "取列表/分类/详情/图片", en: "Fetch mods and images"}
  - kind: call
    to: modecontroller.backend.store.tasks
    label: {zh: "归一化任务结构", en: "Normalise task shapes"}
---
