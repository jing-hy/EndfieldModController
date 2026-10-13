---
uid: b1d0d008
id: modecontroller.backend.launch.guard
parent: modecontroller.backend.launch
tags: [process]
name: {zh: "进程与安全模式", en: "Processes & Safe Modes"}
description:
  zh: >
      进程与那几个重开关：列出运行中的进程、停掉占住我们文件的、进出提权反作弊安全模式与 d3d12 代理模式，并执行游戏单实例限制。
      
  en: >
      Processes and the heavy safety switches: list running processes, stop the ones locking our files, enter/restore the elevated anti-cheat safe mode and the d3d12 proxy mode, and enforce the single-instance rule for the game.
      
revision: d6153bf31b870c1ccd2e00dac49af51793b5267a
updated_at: "2026-10-13T16:02:57.651Z"
fingerprint: 43a32b5be69efb4163acdf02f09c5677cabca0dcf913909a7a1c7457430de4c0
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 138
    end_line: 251
  - path: "endfieldmodcontroller/launcher.py"
    line: 3224
    end_line: 5973
  - path: "endfieldmodcontroller/launcher.py"
    line: 3964
    end_line: 6372
apis:
  - protocol: rpc
    path: "launcher._stop_locked_files_processes"
    description:
      zh: >
          停掉占住我们文件的进程 —— 默认**绝不包含**正在跑的游戏。
          
      en: >
          Stop the processes that lock our files — by default never including the running game.
          
  - protocol: rpc
    path: "launcher.enable_anti_cheat_safe_mode"
    description:
      zh: >
          进出提权反作弊安全模式。
          
      en: >
          Enter / leave the elevated anti-cheat safe mode.
          
  - protocol: rpc
    path: "launcher.check_game_multi_instance"
    description:
      zh: >
          拒绍启动第二个游戏实例（两个实例会抢 D3D 设备与 Mods 目录）。
          
      en: >
          Refuse a second game instance (two instances fight over the D3D device and the Mods folder).
          
---
