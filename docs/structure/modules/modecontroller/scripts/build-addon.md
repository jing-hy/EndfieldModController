---
uid: b1d14003
id: modecontroller.scripts.build-addon
parent: modecontroller.scripts
tags: [build]
name: {zh: "构建面板 addon", en: "Build the Panel Add-on"}
description:
  zh: >
      从源码编译 ReShade add-on 并放到面板部署步骤预期的位置 —— 面板是原生代码，没法以 Python 脚本形式发布。
      
  en: >
      Compile the ReShade add-on from source and drop it where the panel deploy step expects it — the panel is native code, so it cannot ship as a Python script.
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.126Z"
fingerprint: 71e964bcb8e5ff8f6003c41fca2b7fd9df48af20a097a099640ccd194e2facf2
source:
  - path: "scripts/build_addon.py"
    line: 2
    end_line: 127
apis:
  - protocol: rpc
    path: "scripts.build_addon"
    description:
      zh: >
          把 ReShade 面板 add-on 编译好（`/MT /Brepro`）放到部署步骤预期的位置。
          
      en: >
          Compile the ReShade panel add-on (*/MT /Brepro*) into the path the deploy step expects.
          
---
