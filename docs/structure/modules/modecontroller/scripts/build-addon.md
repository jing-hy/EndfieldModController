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
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.934Z"
fingerprint: 2ea681bd331a1f54e2c738aff5461e38721e4c9d86d0fa3a2959ebd20aa8d663
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
