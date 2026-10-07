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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.512Z"
fingerprint: 34750760c764a67386e74fba7177cb0ee04c5662766453fd8e4b5c58b2b45ae1
source:
  - path: "endfieldmodcontroller/dependencies.py"
    line: 124
    end_line: 286
  - path: "endfieldmodcontroller/dependencies.py"
    line: 223
    end_line: 471
  - path: "endfieldmodcontroller/dependencies.py"
    line: 387
    end_line: 604
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
