---
uid: 5f0a0001
id: modecontroller.backend.store
parent: modecontroller.backend
tags: [store, gamebanana, download]
name: {zh: "Mod 商城与下载队列", en: "Mod Store & Download Queue"}
description:
  zh: >
      程序内的 Mod 商城数据层与下载任务模型：从香蕉网（GameBanana）取列表/分类/详情/图片，并把下载任务归一化成统一结构供界面与队列消费。只消费站点的元数据与链接，不镜像、不再分发任何文件。
      
  en: >
      In-app mod store data layer and download-task model: pulls listings, categories, details and images from GameBanana, and normalises download tasks into one shape for the UI and the queue. Consumes metadata and links only; never mirrors or redistributes files.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.260Z"
fingerprint: f5aa921cb381555927035fec410250020a78e764ee81f474dab8378bcf94e46d
source:
  - path: "endfieldmodcontroller/modstore.py"
  - path: "endfieldmodcontroller/downloads.py"
---
