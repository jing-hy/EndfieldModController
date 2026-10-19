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
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.891Z"
fingerprint: df7e8d6a6e453710da48546e320c61515311231f5c10b3943d036db2db3037a2
source:
  - path: "tests/test_dlss5_preset_and_game_dir.py"
    line: 2
    end_line: 264
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
