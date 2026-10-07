---
uid: b1c0b008
id: modecontroller.backend.components
parent: modecontroller.backend
tags: [deps, download]
name: {zh: "组件与资产", en: "Components & Assets"}
description:
  zh: >
      拿到并维护运行时的第三方件：读可编辑的 dependencies.json 清单，下载（带重试与线路切换）、校验 sha256、用 7-Zip 或 Windows 自带 bsdtar 解压 zip/7z/rar、装进 _deps，并维护内置的 XXMI / Libraries / EFMI / Poser / 喂帧组件。
      
  en: >
      Getting and keeping the runtime's third-party pieces: read the editable dependencies.json manifest, download (with retry and line switching), verify sha256, extract zip/7z/rar via 7-Zip or Windows bsdtar, install into _deps, and keep the built-in XXMI / Libraries / EFMI / Poser / DLSS5-feeder components in place.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.335Z"
fingerprint: 3cca7d44bfe6c318ae26463592825db5734875a8c48a3269ea979e3b59c8afbe
source:
  - path: "endfieldmodcontroller/dependencies.py"
  - path: "endfieldmodcontroller/runtime_deps.py"
  - path: "endfieldmodcontroller/runtime_assets.py"
---
