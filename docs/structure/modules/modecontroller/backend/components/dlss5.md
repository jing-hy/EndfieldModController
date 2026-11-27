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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.076Z"
fingerprint: c3e781c8090e08990f9ab31e4cb8d982f56f5e7495ea3d6c3ee4c2b2c2b27e78
source:
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 51
    end_line: 302
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 225
    end_line: 747
  - path: "endfieldmodcontroller/dlss5_fetcher.py"
    line: 414
    end_line: 1099
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
