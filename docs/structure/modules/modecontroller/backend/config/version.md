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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.028Z"
fingerprint: 8f1282d6321fc0af776e4fa2f28ef59565dfefaf2159d419cfa5a79c90bfc226
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
