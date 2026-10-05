---
uid: b1d11003
id: modecontroller.backend.components.install
parent: modecontroller.backend.components
tags: [install]
name: {zh: "安装与批量更新", en: "Install & Batch Update"}
description:
  zh: >
      把下回来的包放到该放的地方：校验安装目录名是否安全、从解压树安装、验收结果，并用带重试与进度回调（供界面轮询）的方式批量跑完整条。
      
  en: >
      Put a downloaded archive where it belongs: sanity-check the install directory name, install from the extracted tree, verify the result, and drive the whole thing in batches with retry and a progress callback the UI can poll.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.300Z"
fingerprint: c5a6bc8c96ea19c3ce68250b0a79b8b549942c7450c986a8b6e1f5f9ec8e1883
source:
  - path: "endfieldmodcontroller/dependencies.py"
    line: 493
    end_line: 600
  - path: "endfieldmodcontroller/dependencies.py"
    line: 543
    end_line: 746
apis:
  - protocol: rpc
    path: "install_from_archive"
    description:
      zh: >
          从解压树安装到**校验过的**安装目录（只允许落在库的 `_deps\` 之内）。
          
      en: >
          Install from an extracted tree into a validated install directory (only inside the library's _deps).
          
  - protocol: rpc
    path: "update_dependency"
    description:
      zh: >
          端到端安装或更新单个依赖。
          
      en: >
          Install or update one dependency end to end.
          
  - protocol: rpc
    path: "update_all"
    description:
      zh: >
          跑完整批：先把所有项都试一遍，再对失败项最多重试 3 次。
          
      en: >
          Run the whole batch: try everything once, then retry the failures up to 3 times.
          
deps:
  - kind: call
    to: modecontroller.backend.components.download
    label: {zh: "要先有包", en: "Needs the archive"}
---
