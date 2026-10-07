---
uid: b1d15004
id: modecontroller.tests.dlss5
parent: modecontroller.tests
tags: [tests]
name: {zh: "DLSS5 与 ReShade 测试", en: "DLSS5 & ReShade Tests"}
description:
  zh: >
      DLSS5 / ReShade 侧测试：NRStyle 只报不改的规则、生成 preset 时不砸掉 ReShade 自己的标记、游戏自带 DLSS 时自动停喂帧、游戏目录与渲染 API 探测、显卡代次默认值，以及 OptiScaler 处理。
      
  en: >
      Tests for the DLSS5 / ReShade side: the NRStyle report-only rule, preset generation without clobbering ReShade's own flags, feed auto-disable on native DLSS, game-dir and render-api detection, GPU generation defaults, and OptiScaler handling.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.276Z"
fingerprint: 1a5c8d2d24b52e8000e510a634ff4b7f996f1ae2840a80f79583a9dc241538d7
source:
  - path: "tests/test_dlss5_preset_and_game_dir.py"
    line: 1
    end_line: 262
  - path: "tests/test_dlss5_nrstyle.py"
    line: 1
    end_line: 140
  - path: "tests/test_reshade_integration.py"
    line: 1
    end_line: 215
  - path: "tests/test_optiscaler_and_clean.py"
    line: 1
    end_line: 131
apis: []
---
