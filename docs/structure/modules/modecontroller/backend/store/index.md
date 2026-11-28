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
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.798Z"
fingerprint: 9b910c52b09282bf1939444511c36b18200980a7c4a86a16baeb3dc7e61ec2a3
source:
  - path: "endfieldmodcontroller/modstore.py"
  - path: "endfieldmodcontroller/downloads.py"
---
