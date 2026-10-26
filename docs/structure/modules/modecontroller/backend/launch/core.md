---
uid: b1d0d001
id: modecontroller.backend.launch.core
parent: modecontroller.backend.launch
tags: [launch]
name: {zh: "启动序列", en: "Launch Sequence"}
description:
  zh: >
      启动序列本体：拼环境与命令行、决定普通还是提权拉起、等 XXMI 界面、再盯游戏进程；另含用户确认前走的那条预览路径。
      
  en: >
      The launch sequence itself: build the environment and command line, pick normal vs elevated spawn, wait for the XXMI GUI, then watch the game process; plus the preview path used before the user commits.
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.384Z"
fingerprint: d24ff6d065e2d2ae29d9f3cfa841b9f9b1330967f599ea40c80b130ce5fe0efd
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 3588
    end_line: 6107
  - path: "endfieldmodcontroller/launcher.py"
    line: 3925
    end_line: 6388
  - path: "endfieldmodcontroller/launcher.py"
    line: 4020
    end_line: 6616
apis:
  - protocol: rpc
    path: "launcher.launch"
    description:
      zh: >
          启动序列本体：环境、命令行、普通还是提权拉起、等 XXMI、再盯游戏进程。
          
      en: >
          The launch sequence itself: env, command line, normal vs elevated spawn, wait for XXMI, then watch the game.
          
  - protocol: rpc
    path: "launcher.launch_official_gui"
    description:
      zh: >
          拉起官方 XXMI 界面（`startfile` 前最后一刻会再补写一次配置）。
          
      en: >
          Bring up the official XXMI GUI (with a last-moment config re-write before startfile).
          
  - protocol: rpc
    path: "launcher.build_launch_env"
    description:
      zh: >
          拼出一次启动所需的环境（路径、ReShade 重定向、清理策略）。
          
      en: >
          Assemble the environment a launch needs (paths, ReShade redirection, cleanup policy).
          
deps:
  - kind: call
    to: modecontroller.backend.launch.injection-lib
    label: {zh: "先保注入库就绪", en: "Ensures injections"}
  - kind: call
    to: modecontroller.backend.components
    label: {zh: "补缺失依赖", en: "Installs deps"}
---
