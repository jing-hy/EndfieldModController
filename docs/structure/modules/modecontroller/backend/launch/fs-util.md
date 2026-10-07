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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.522Z"
fingerprint: e6caf67402aa640892ab0f595aed44045002c053eb58f71cc2467be001d1956a
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 30
    end_line: 51
  - path: "endfieldmodcontroller/launcher.py"
    line: 340
    end_line: 4022
  - path: "endfieldmodcontroller/launcher.py"
    line: 1983
    end_line: 4563
  - path: "endfieldmodcontroller/launcher.py"
    line: 3787
    end_line: 6228
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
