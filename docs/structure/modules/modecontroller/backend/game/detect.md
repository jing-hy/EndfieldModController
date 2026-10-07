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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.517Z"
fingerprint: 09ca401ab6e7fda97dc608eb873f5ff95c8fa44602ea3193d25a8f2373ed5b46
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 784
    end_line: 1505
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 910
    end_line: 1917
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 2163
    end_line: 3181
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
