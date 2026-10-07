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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.515Z"
fingerprint: 01bd48cd209b30b946bf909ee7b15d2409cad6bb1387a3751da43fdfe3f70044
source:
  - path: "endfieldmodcontroller/version.py"
    line: 1
    end_line: 190
apis:
  - protocol: rpc
    path: "version.__version__"
    description:
      zh: >
          程序版本号 —— 自更新、发布脚本与界面比的都是这一个字符串。
          
      en: >
          The program version — the updated copies, the release scripts and the UI all compare against this one string.
          
---
