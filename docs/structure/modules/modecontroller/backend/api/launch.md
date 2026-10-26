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
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.193Z"
fingerprint: f31bee9531d0ff28b4d87e491a4b5aa98279dec04fe11ecb4dbad2aec66c2c37
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2466
    end_line: 5118
  - path: "endfieldmodcontroller/api.py"
    line: 3648
    end_line: 9806
  - path: "endfieldmodcontroller/api.py"
    line: 4734
    end_line: 13501
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
