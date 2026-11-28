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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.892Z"
fingerprint: a50333d9d987eaa35d4db5d326fc5a35b97a7e2fe28d37d2b0515c9756dfce7f
source:
  - path: "endfieldmodcontroller/dependencies.py"
  - path: "endfieldmodcontroller/runtime_deps.py"
  - path: "endfieldmodcontroller/runtime_assets.py"
---
