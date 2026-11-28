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
      
revision: 5b034875dd0ea08fcd1a78982c72969af5d72139
updated_at: "2026-11-28T15:58:50.111Z"
fingerprint: d13f304007971f4624bf1045f2a68c3ba48bac5050d3e00fe6b851831c7ed28a
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 4443
    end_line: 7817
  - path: "endfieldmodcontroller/launcher.py"
    line: 4780
    end_line: 8098
  - path: "endfieldmodcontroller/launcher.py"
    line: 4875
    end_line: 8326
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
