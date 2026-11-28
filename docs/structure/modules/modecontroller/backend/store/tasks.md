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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.896Z"
fingerprint: dfb3282d44041b1dd0a46b80ebeb1c0d0acd5ff9667d406227db335ab34d447d
source:
  - path: "endfieldmodcontroller/downloads.py"
apis: []
---
