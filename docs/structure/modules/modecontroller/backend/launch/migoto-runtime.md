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
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.779Z"
fingerprint: 8b52918c0df826375bcd7e5121c69a478bc896289d5de2a29d1e0cff349704d8
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 57
    end_line: 141
  - path: "endfieldmodcontroller/launcher.py"
    line: 4456
    end_line: 7865
  - path: "endfieldmodcontroller/launcher.py"
    line: 5117
    end_line: 8485
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
