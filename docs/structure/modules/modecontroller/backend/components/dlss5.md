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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.334Z"
fingerprint: 8dbef670d67c42325a0dea95fb4ce2aafc24a49e6efa33f95c82262de1aa9db0
source:
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 50
    end_line: 300
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 224
    end_line: 677
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 393
    end_line: 1029
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
