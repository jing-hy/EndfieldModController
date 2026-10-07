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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.230Z"
fingerprint: 4462b017d034d09265588504bd2bedfa9b2c5b5b92c66dfe183c0a1cf4f67045
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
