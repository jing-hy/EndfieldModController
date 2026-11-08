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
      
revision: 98e1fd157ee785be02b700a7086f9d8f77b037de
updated_at: "2026-11-08T02:13:35.803Z"
fingerprint: 04604dab2c1fad9d16fe99638e79f6d82d8fd072958cef4788e54cb3e10fe78c
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
