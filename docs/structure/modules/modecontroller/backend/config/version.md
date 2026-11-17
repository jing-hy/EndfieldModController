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
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.091Z"
fingerprint: eb93805849a5f6402ff7c9c9ad576d871fe7e62c9fef91d5cdb796cbcb77ebd8
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
