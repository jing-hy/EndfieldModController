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
      
revision: 89bc0c73458ae7cf701d5c51691a28cfbebc2135
updated_at: "2026-11-07T05:15:40.225Z"
fingerprint: 997036629ba2d890a91cb3d98445d9909ff81de0e71110fc5e45f2cea6cfbb87
source:
  - path: "endfieldmodcontroller/version.py"
    line: 2
    end_line: 196
apis:
  - protocol: rpc
    path: "version.__version__"
    description:
      zh: >
          程序版本号 —— 自更新、发布脚本与界面比的都是这一个字符串。
          
      en: >
          The program version — the updated copies, the release scripts and the UI all compare against this one string.
          
---
