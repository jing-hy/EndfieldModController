---
uid: b1d0d007
id: modecontroller.backend.launch.migoto-runtime
parent: modecontroller.backend.launch
tags: [loader]
name: {zh: "loader 运行时", en: "Loader Runtime"}
description:
  zh: >
      真正干注入的 loader：把运行时摆到游戏旁边、告诉 d3dx 用哪个 loader 目标、拉起多开 loader exe —— 含识别并迁移旧的框架布局。
      
  en: >
      The loader that actually injects: assemble the runtime beside the game, tell d3dx which loader target to use, and start the multi-loader exe — including detecting and migrating the legacy framework layout.
      
revision: 55d938448b4178c517e948237ce04bb8fda54fbe
updated_at: "2026-10-12T14:48:34.220Z"
fingerprint: 43a32b5be69efb4163acdf02f09c5677cabca0dcf913909a7a1c7457430de4c0
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 56
    end_line: 139
  - path: "endfieldmodcontroller/launcher.py"
    line: 3526
    end_line: 6005
  - path: "endfieldmodcontroller/launcher.py"
    line: 4187
    end_line: 6625
apis:
  - protocol: rpc
    path: "launcher.ensure_migoto_runtime"
    description:
      zh: >
          把 loader 运行时摆到游戏旁边；发现旧框架布局就顺手迁移。
          
      en: >
          Assemble the loader runtime beside the game, migrating the legacy framework layout if found.
          
  - protocol: rpc
    path: "launcher.launch_migoto_loader"
    description:
      zh: >
          拉起多开 loader exe。
          
      en: >
          Start the multi-loader exe.
          
---
