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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.523Z"
fingerprint: e6caf67402aa640892ab0f595aed44045002c053eb58f71cc2467be001d1956a
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 55
    end_line: 137
  - path: "endfieldmodcontroller/launcher.py"
    line: 3509
    end_line: 5971
  - path: "endfieldmodcontroller/launcher.py"
    line: 4170
    end_line: 6591
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
