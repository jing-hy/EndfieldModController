---
uid: 5f0a0004
id: modecontroller.backend.api.store
parent: modecontroller.backend.api
tags: [api, store, download]
name: {zh: "商城与下载中心接口", en: "Store & Download APIs"}
description:
  zh: >
      商城主流程与下载中心的 js_api 面：列表/分类/详情/备图/索引刷新/批量扫描与一键更新，以及下载任务的快照、暂停、继续、取消、清空。列表与分类数字同源于本地索引；索引刷新是后台任务，状态行如实报"就绪 / 不完整 / 用了旧索引"。下载动作只入队不跳转。
      
  en: >
      js_api surface for the store flow and the download centre: listing, categories, detail, images, index refresh, batch scan and update-all, plus download task control. List and category counts share the local index; index refresh is a background task with an honest status line. Enqueues instead of navigating.
      
revision: 89ad502e368be7ee5b8c45c1a4d735e1870f43b9
updated_at: "2026-11-07T04:43:41.667Z"
fingerprint: 43275d255d70e23ea5822f87048fcf96695312ae473eb9e4d2e8649ba2981d89
source:
  - path: "endfieldmodcontroller/api.py"
apis:
  - protocol: rpc
    path: "mod_store_list"
    description:
      zh: >
          商城列表（分页/分类/角色/排序/R18 三档，附与列表同源的分类计数）
          
      en: >
          Store listing with filters, R18 tri-state and index-derived category counts
          
  - protocol: rpc
    path: "mod_store_categories"
    description:
      zh: >
          分类树与角色名单（中文名；数字以本地索引为准）
          
      en: >
          Category tree and characters (Chinese names; counts from the local index)
          
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
    path: "mod_store_prefetch"
    description:
      zh: >
          后台补全/刷新全量索引（残缺时缩短重试间隔，状态行如实报条数）
          
      en: >
          Background index refresh (short retry when incomplete, honest status)
          
  - protocol: rpc
    path: "mod_store_refresh_index"
    description:
      zh: >
          强制重建全量索引（"少的 Mod 不见了"时的恢复入口）
          
      en: >
          Force a full index rebuild (recovery entry)
          
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
