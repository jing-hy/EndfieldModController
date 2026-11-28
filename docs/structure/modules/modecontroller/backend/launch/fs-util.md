---
uid: b1d0d009
id: modecontroller.backend.launch.fs-util
parent: modecontroller.backend.launch
tags: [util]
name: {zh: "原子写与小工具", en: "Atomic IO & Helpers"}
description:
  zh: >
      小但吃重的小工具：只在内容变了才拷、带唯一备份的原子写文件/ini、图像进程探测、热键接管判定，以及每个启动步骤都用的日志落盘入口。
      
  en: >
      Small but load-bearing helpers: copy only when content changed, atomic file/ini writes with unique backups, image-process probing, hotkey-takeover resolution, and the append-to-log sink used by every launch step.
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:56.996Z"
fingerprint: 3157c48139c85ce9af179ef5b8b380ae1aade7329205bd4bf4ce61b20d5894a9
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 32
    end_line: 55
  - path: "endfieldmodcontroller/launcher.py"
    line: 742
    end_line: 5818
  - path: "endfieldmodcontroller/launcher.py"
    line: 2470
    end_line: 6359
  - path: "endfieldmodcontroller/launcher.py"
    line: 4685
    end_line: 8024
apis:
  - protocol: rpc
    path: "_copy_if_changed"
    description:
      zh: >
          只在内容变了才拷（所有推进游戏目录的文件都走它）。
          
      en: >
          Copy only when content changed (used for every file we push into the game folder).
          
  - protocol: rpc
    path: "_write_ini_atomic"
    description:
      zh: >
          游戏目录 ini 的原子写，并只留一次 `.mc.bak` 备份。
          
      en: >
          Atomic write for game-folder inis, with a one-time .mc.bak alongside.
          
  - protocol: rpc
    path: "resolve_hotkey_takeover"
    description:
      zh: >
          判定此刻能不能接管热键（要能证明面板确实已部署）。
          
      en: >
          Decide whether hotkey takeover is allowed right now (proves the panel is really deployed).
          
---
