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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.861Z"
fingerprint: 3d110ab16f214d7c1a524fb4b298482cc28922d0a3935749069261d570ba0d03
source:
  - path: "endfieldmodcontroller/dependencies.py"
    line: 521
    end_line: 656
  - path: "endfieldmodcontroller/dependencies.py"
    line: 571
    end_line: 802
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
