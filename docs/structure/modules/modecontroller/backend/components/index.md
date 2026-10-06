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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.960Z"
fingerprint: 517b78f82010ac17f9c9062e70533f84b6a64329517c1ef80017ecd6cf8798c1
source:
  - path: "endfieldmodcontroller/dependencies.py"
  - path: "endfieldmodcontroller/runtime_deps.py"
  - path: "endfieldmodcontroller/runtime_assets.py"
---
