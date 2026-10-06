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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.985Z"
fingerprint: 4e33b0eb51cf1544afc128a174fee7e584cd88735c387a4c5437823b050ea3f9
source:
  - path: "scripts/build_addon.py"
    line: 1
    end_line: 125
apis:
  - protocol: rpc
    path: "scripts.build_addon"
    description:
      zh: >
          把 ReShade 面板 add-on 编译好（`/MT /Brepro`）放到部署步骤预期的位置。
          
      en: >
          Compile the ReShade panel add-on (*/MT /Brepro*) into the path the deploy step expects.
          
---
