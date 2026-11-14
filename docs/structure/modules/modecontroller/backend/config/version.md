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
      
revision: 5ad99916cdff1745b2f88ff3fa46f4116ff95157
updated_at: "2026-11-14T05:47:42.737Z"
fingerprint: dd8847ee74f9e2af70cdbec2746b701bf992539dcb1e4e05c6f00dce0954e285
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
