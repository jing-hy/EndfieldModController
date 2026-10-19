---
uid: b1d12008
id: modecontroller.backend.config.version
parent: modecontroller.backend.config
tags: [version]
name: {zh: "版本常量", en: "Version Constants"}
description:
  zh: >
      程序版本号与仓库坐标的唯一定义处 —— 自更新、发布脚本与界面比对的都是同一个字符串。
      
  en: >
      The one place the program's version number and repository coordinates live — so the updater, the release scripts and the UI all compare against the same string.
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.860Z"
fingerprint: cbc48a87643866c177a822a0669dc89b7c405f639b606c2205f3e0ed2fdf8f7f
source:
  - path: "endfieldmodcontroller/version.py"
    line: 2
    end_line: 192
apis:
  - protocol: rpc
    path: "version.__version__"
    description:
      zh: >
          程序版本号 —— 自更新、发布脚本与界面比的都是这一个字符串。
          
      en: >
          The program version — the updated copies, the release scripts and the UI all compare against this one string.
          
---
