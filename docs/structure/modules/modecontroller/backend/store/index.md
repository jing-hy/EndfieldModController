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
      
revision: 89bc0c73458ae7cf701d5c51691a28cfbebc2135
updated_at: "2026-11-07T05:15:40.252Z"
fingerprint: b6599d4c42d3c93309778ab6065573794265664a84e1195a9c8a4cb286b9fc0f
source:
  - path: "endfieldmodcontroller/modstore.py"
  - path: "endfieldmodcontroller/downloads.py"
---
