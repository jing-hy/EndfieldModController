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
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.869Z"
fingerprint: d24ff6d065e2d2ae29d9f3cfa841b9f9b1330967f599ea40c80b130ce5fe0efd
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 56
    end_line: 139
  - path: "endfieldmodcontroller/launcher.py"
    line: 3541
    end_line: 6035
  - path: "endfieldmodcontroller/launcher.py"
    line: 4202
    end_line: 6655
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
