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
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.803Z"
fingerprint: f2ec8bab5b84939a5ed7df4c5a7a8fd4e460ef89eb909be4468e53e7ef777339
source:
  - path: "endfieldmodcontroller/version.py"
    line: 2
    end_line: 200
apis:
  - protocol: rpc
    path: "version.__version__"
    description:
      zh: >
          程序版本号 —— 自更新、发布脚本与界面比的都是这一个字符串。
          
      en: >
          The program version — the updated copies, the release scripts and the UI all compare against this one string.
          
---
