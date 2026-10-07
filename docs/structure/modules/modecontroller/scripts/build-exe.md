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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.354Z"
fingerprint: 8988209187d1a4e80a700a2f9ad53dbbaac07f19b8e484b75e0448405857a341
source:
  - path: "scripts/build_exe.py"
    line: 1
    end_line: 164
apis:
  - protocol: rpc
    path: "scripts.build_exe"
    description:
      zh: >
          用发布版一模一样的那套参数构建单文件 exe（onefile、无控制台、管理员清单、内嵌 web 资源）。
          
      en: >
          Build the single-file exe (*-onefile*, windowed, admin manifest, web assets embedded) with the exact flag set the shipped binary uses.
          
---
