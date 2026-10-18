---
uid: 5f0a0003
id: modecontroller.backend.store.tasks
parent: modecontroller.backend.store
tags: [download, task, normalise]
name: {zh: "下载任务整形", en: "Download Task Model"}
description:
  zh: >
      把 Mod 下载与组件下载两类任务归一化成同一结构（状态、进度、速度、日志尾巴、封面），供下载页的任务列表与侧栏活跃数徽标共同消费。纯整形，不含任何下载或网络动作。
      
  en: >
      Normalises Mod downloads and component downloads into one task shape (status, progress, speed, log tail, cover) consumed by the downloads page and the sidebar badge. Pure shaping; performs no downloading.
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.927Z"
fingerprint: 03866e898b882f0195909b56a747a6183d2b18613b92c1d3c068fda260480155
source:
  - path: "endfieldmodcontroller/downloads.py"
apis: []
---
