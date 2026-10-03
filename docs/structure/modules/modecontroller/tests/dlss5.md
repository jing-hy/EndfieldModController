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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.328Z"
fingerprint: f13f3d95350d5ff54e7392fba93e139e5e1664a66e90370d4f63c7084fd74a32
source:
  - path: "tests/test_dlss5_preset_and_game_dir.py"
    line: 1
    end_line: 242
  - path: "tests/test_dlss5_nrstyle.py"
    line: 1
    end_line: 140
  - path: "tests/test_reshade_integration.py"
    line: 1
    end_line: 197
  - path: "tests/test_optiscaler_and_clean.py"
    line: 1
    end_line: 131
apis: []
---
