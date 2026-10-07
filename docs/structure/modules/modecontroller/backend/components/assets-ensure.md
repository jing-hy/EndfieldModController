---
uid: b1d11006
id: modecontroller.backend.components.assets-ensure
parent: modecontroller.backend.components
tags: [assets]
name: {zh: "资产修复与打包", en: "Asset Repair & Bundle"}
description:
  zh: >
      按需把必需文件就位：解开分片载荷、从 Release 拉资产包、展开、验收 —— 也就是“运行时文件被删或损坏”时走的那条修复路径。
      
  en: >
      Get a required file into place on demand: decompress multi-part payloads, fetch the assets bundle from the release, extract it, and verify — the path that repairs a runtime whose files were deleted or corrupted.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.333Z"
fingerprint: 2bbba29349acd1c14694f1d3400361a35c9053844fd4f3b91d4d643e5f8da5b9
source:
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 853
    end_line: 2175
  - path: "endfieldmodcontroller/runtime_assets.py"
    line: 1206
    end_line: 2632
apis:
  - protocol: rpc
    path: "ensure_file"
    description:
      zh: >
          把某个必需资产文件就位，必要时解开分片载荷。
          
      en: >
          Get one required asset file into place, decompressing multi-part payloads if needed.
          
  - protocol: rpc
    path: "ensure_all"
    description:
      zh: >
          逐项检查随包资产，缺的就补。
          
      en: >
          Check every bundled asset and repair what is missing.
          
  - protocol: rpc
    path: "fetch_bundle"
    description:
      zh: >
          从 Release 拉取并展开 assets-bundle.zip（带网页+镜像回退）。
          
      en: >
          Fetch and extract assets-bundle.zip from the release (with web+mirror fallback).
          
deps:
  - kind: call
    to: modecontroller.backend.components.assets-baseline
    label: {zh: "对照基线", en: "Checks the baseline"}
---
