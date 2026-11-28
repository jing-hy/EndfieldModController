---
uid: b1d10006
id: modecontroller.backend.game.detect
parent: modecontroller.backend.game
tags: [detect]
name: {zh: "游戏目录与渲染 API 探测", en: "Game Dir & API Detection"}
description:
  zh: >
      动手之前先把事实查清：找到真正的游戏目录（配置、XXMI 配置、XXMI 日志三条路），判出游戏用哪个渲染 API，并识别已有的 ReShade 而不是与它硬碰。
      
  en: >
      Work out the facts before touching anything: find the real game directory (config, XXMI config, XXMI log), detect which render API the game uses, and detect an already-installed ReShade rather than fighting it.
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:56.991Z"
fingerprint: 0349ed6888285bb3f99b53390aa868f8ad657a9499de5d67c34e63214c7c3653
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 807
    end_line: 1551
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 933
    end_line: 2041
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 2225
    end_line: 3305
apis:
  - protocol: rpc
    path: "reshade_integration.detect_game_dir"
    description:
      zh: >
          找出真正的游戏目录：遍历导入器、官方启动器、XXMI 日志与扫盘四条路。
          
      en: >
          Find the real game directory by walking importers, the official launcher, the XXMI log and a drive scan.
          
  - protocol: rpc
    path: "reshade_integration.detect_render_api"
    description:
      zh: >
          判出游戏实际用的渲染 API。
          
      en: >
          Detect which render API the game is actually using.
          
  - protocol: rpc
    path: "reshade_integration.detect_existing_reshade"
    description:
      zh: >
          识别已有的 ReShade，而不是与它硬碰。
          
      en: >
          Detect an already-installed ReShade instead of fighting it.
          
---
