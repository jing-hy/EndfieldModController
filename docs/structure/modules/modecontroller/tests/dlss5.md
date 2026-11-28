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
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.018Z"
fingerprint: b4c9c1af82e7344de461ccfb34cd6ea11d710225aac71af1c9ab27310d4609a2
source:
  - path: "tests/test_dlss5_preset_and_game_dir.py"
    line: 1
    end_line: 143
  - path: "tests/test_dlss5_nrstyle.py"
    line: 2
    end_line: 142
  - path: "tests/test_reshade_integration.py"
    line: 2
    end_line: 217
  - path: "tests/test_optiscaler_and_clean.py"
    line: 2
    end_line: 133
apis: []
---
