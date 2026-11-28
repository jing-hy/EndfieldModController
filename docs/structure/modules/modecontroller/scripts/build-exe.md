---
uid: b1d14001
id: modecontroller.scripts.build-exe
parent: modecontroller.scripts
tags: [build]
name: {zh: "构建 exe", en: "Build the EXE"}
description:
  zh: >
      用 PyInstaller 构建单文件 exe：一整套写死的参数（one-file、无控制台、内嵌 web 资源、管理员清单、内嵌 webview/clr/cryptography）—— 发布的那份必须就是用它构建的。
      
  en: >
      Build the single-file exe with PyInstaller: the exact flag set (one-file, windowed, bundled web assets, admin manifest, bundled webview/clr/cryptography) that the shipped binary has to be built with.
      
revision: b124e58720a8b882c922f28505d3d1412c494693
updated_at: "2026-11-28T17:22:47.846Z"
fingerprint: 9c4329f3eafdb4fbf325b7e498081d1131ede8b754c856183cde61d514bf099f
source:
  - path: "scripts/build_exe.py"
    line: 2
    end_line: 1390
apis:
  - protocol: rpc
    path: "scripts.build_exe"
    description:
      zh: >
          用发布版一模一样的那套参数构建单文件 exe（onefile、无控制台、管理员清单、内嵌 web 资源）。
          
      en: >
          Build the single-file exe (*-onefile*, windowed, admin manifest, web assets embedded) with the exact flag set the shipped binary uses.
          
---
