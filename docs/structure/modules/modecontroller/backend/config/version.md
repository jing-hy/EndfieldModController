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
      
revision: 89ad502e368be7ee5b8c45c1a4d735e1870f43b9
updated_at: "2026-11-07T04:43:41.671Z"
fingerprint: 15d7f8ba84052b4f096c148b1f4573d6738aa8e86116946cc641c3dea377f409
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
