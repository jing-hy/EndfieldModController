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
      
revision: 55d938448b4178c517e948237ce04bb8fda54fbe
updated_at: "2026-10-12T14:48:34.248Z"
fingerprint: de8bf5aab98c34777b990371e4b4764190eb2920e7c7959bdfc40b71173c0051
source:
  - path: "scripts/build_exe.py"
    line: 2
    end_line: 204
apis:
  - protocol: rpc
    path: "scripts.build_exe"
    description:
      zh: >
          用发布版一模一样的那套参数构建单文件 exe（onefile、无控制台、管理员清单、内嵌 web 资源）。
          
      en: >
          Build the single-file exe (*-onefile*, windowed, admin manifest, web assets embedded) with the exact flag set the shipped binary uses.
          
---
