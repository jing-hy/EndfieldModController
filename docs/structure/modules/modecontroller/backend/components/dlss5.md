---
uid: b1d11007
id: modecontroller.backend.components.dlss5
parent: modecontroller.backend.components
tags: [dlss5]
name: {zh: "DLSS5 组件", en: "DLSS5 Components"}
description:
  zh: >
      DLSS5 的几个子件（ReShade 底座、喂帧 addon、iMMERSE）：逐组件标记、与上游比版本、从 release 里挑资产，以及在游戏旁边原子写入的安装器。
      
  en: >
      The DLSS5 sub-components (ReShade base, the feed add-on, iMMERSE): per-component markers, version comparison against upstream, asset picking from the release, and the installers that write files atomically beside the game.
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.732Z"
fingerprint: 3b1c1d35581af4754ca3dae5406b46a90f17d7f7f7561cd284b8d34068ee7681
source:
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 51
    end_line: 314
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 231
    end_line: 777
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 420
    end_line: 1129
apis:
  - protocol: rpc
    path: "component_report"
    description:
      zh: >
          DLSS5 子组件的逐项状态（ReShade 底座 / 喂帧 addon / iMMERSE）。
          
      en: >
          Per-component state for the DLSS5 sub-components (ReShade base / feed add-on / iMMERSE).
          
  - protocol: rpc
    path: "check_updates"
    description:
      zh: >
          把已装版本与上游比，说出哪些能更新。
          
      en: >
          Compare installed versions against upstream and say what can update.
          
  - protocol: rpc
    path: "install"
    description:
      zh: >
          安装指定的单个 DLSS5 子组件。
          
      en: >
          Install one named DLSS5 sub-component.
          
deps:
  - kind: call
    to: modecontroller.backend.components.download
    label: {zh: "用下载器", en: "Uses downloader"}
---
