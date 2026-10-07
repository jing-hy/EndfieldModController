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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.352Z"
fingerprint: 00f709dc1363f858c65f32e4695f5550ad4819d3af4bec4ec307750047a62460
source:
  - path: "endfieldmodcontroller/modstore.py"
  - path: "endfieldmodcontroller/downloads.py"
---
