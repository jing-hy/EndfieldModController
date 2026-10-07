---
uid: b1d0c005
id: modecontroller.backend.api.launch
parent: modecontroller.backend.api
tags: [api, launch]
name: {zh: "启动与预览", en: "Launch & Preview"}
description:
  zh: >
      让游戏跑起来的那一整条：中转准备、启动前预览（会加载什么、查到什么风险），以及官方界面 / migoto loader / 游戏本体的启动入口，加上强制关闭与“是否在跑”的探询。
      
  en: >
      Everything that gets the game running: stage-and-prepare, the pre-launch preview payload (what will be staged, what risks were found), and the launch entries for the official GUI, the migoto loader and the game itself, plus force-close and the running-state probes.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.329Z"
fingerprint: ccf7e6da62fbc5fd85c1836a1d4e69d7b5520a7f3320ac3dddf0ca06aae773bb
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2071
    end_line: 3772
  - path: "endfieldmodcontroller/api.py"
    line: 2975
    end_line: 8042
  - path: "endfieldmodcontroller/api.py"
    line: 4061
    end_line: 11737
apis:
  - protocol: rpc
    path: "prepare"
    description:
      zh: >
          只做中转与准备、不启动（预览用）。
          
      en: >
          Stage and prepare everything without launching (used by the preview).
          
  - protocol: rpc
    path: "prepare_launch"
    description:
      zh: >
          启动前预览包：会加载什么，以及查到的风险。
          
      en: >
          The pre-launch preview payload: what will be staged, plus any risks found.
          
  - protocol: rpc
    path: "launch_official_gui"
    description:
      zh: >
          拉起官方 XXMI 界面（正常的一键启动路径）。
          
      en: >
          Launch the official XXMI GUI (the normal one-click path).
          
  - protocol: rpc
    path: "launch_migoto_loader"
    description:
      zh: >
          经 migoto loader 启动游戏（另一条路径）。
          
      en: >
          Launch the game through the migoto loader (alternate path).
          
  - protocol: rpc
    path: "force_close_game"
    description:
      zh: >
          强制关掉挡住我们的残留游戏/XXMI 进程。
          
      en: >
          Force-close leftover game or XXMI processes that block us.
          
  - protocol: rpc
    path: "game_running"
    description:
      zh: >
          XXMI 在跑吗 / 游戏在跑吗。
          
      en: >
          Is XXMI running / is the game running.
          
deps:
  - kind: call
    to: modecontroller.backend.launch
    label: {zh: "先中转再启动", en: "Stages then launches"}
---
