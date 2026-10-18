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
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.092Z"
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
