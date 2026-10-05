---
uid: b1d11002
id: modecontroller.backend.components.download
parent: modecontroller.backend.components
tags: [download]
name: {zh: "下载与解压", en: "Fetch & Extract"}
description:
  zh: >
      把压缩包拿回来：带重试与降级回退的 HTTP、稳定下载缓存（慢网用户不会为了同一份文件重下一次）、GameBanana 最新文件查询，以及按机器情况用 7-Zip 或系统自带 bsdtar 解压。
      
  en: >
      Fetch archives: HTTP with retry and legacy fallback, a stable download cache so a slow connection never re-downloads the same file, GameBanana's latest-file lookup, and extraction via 7-Zip or the bundled Windows bsdtar depending on what the machine has.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.299Z"
fingerprint: c5a6bc8c96ea19c3ce68250b0a79b8b549942c7450c986a8b6e1f5f9ec8e1883
source:
  - path: "endfieldmodcontroller/dependencies.py"
    line: 124
    end_line: 241
  - path: "endfieldmodcontroller/dependencies.py"
    line: 217
    end_line: 417
  - path: "endfieldmodcontroller/dependencies.py"
    line: 360
    end_line: 550
apis:
  - protocol: rpc
    path: "_download"
    description:
      zh: >
          带重试、降级回退与**稳定下载缓存**的 HTTP 获取（慢网用户不会为同一份文件重下）。
          
      en: >
          HTTP fetch with retry, legacy fallback and a stable download cache (a slow line never re-downloads the same file).
          
  - protocol: rpc
    path: "extract_archive"
    description:
      zh: >
          用这台机器有的工具（7-Zip 或 Windows bsdtar）解压 zip / 7z / rar。
          
      en: >
          Extract zip / 7z / rar using whichever tool this machine has (7-Zip or Windows bsdtar).
          
  - protocol: rpc
    path: "find_archive_tool"
    description:
      zh: >
          按优先级找出可用的解压工具。
          
      en: >
          Which archive tool is available, in priority order.
          
deps:
  - kind: call
    to: modecontroller.backend.components.manifest
    label: {zh: "读清单", en: "Reads the manifest"}
---
