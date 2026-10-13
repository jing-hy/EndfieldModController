---
uid: b1d15003
id: modecontroller.tests.launch
parent: modecontroller.tests
tags: [tests]
name: {zh: "启动与面板测试", en: "Launch & Panel Tests"}
description:
  zh: >
      启动路径的测试：界面调用的那层 api、生成出来的 controller.ini 体检、统一热键面板协议，以及一次离线端到端跑 —— 启动期的回归在用户之前就被它拦住。
      
  en: >
      Tests for the launch path: the api surface the UI calls, linting the generated controller ini, the unified hotkey panel protocol, and one offline end-to-end run — the suite that would catch a launch-time regression before a user does.
      
revision: d6153bf31b870c1ccd2e00dac49af51793b5267a
updated_at: "2026-10-13T16:02:57.673Z"
fingerprint: b0eb7276a88dd0dfefbc6dfc815448b66412a69b760e6f6980af9a69fa992fba
source:
  - path: "tests/test_launcher_api.py"
    line: 2
    end_line: 288
  - path: "tests/test_hotkey_panel.py"
    line: 2
    end_line: 2759
  - path: "tests/test_controller_ini_lint.py"
    line: 2
    end_line: 68
  - path: "tests/test_e2e_offline.py"
    line: 2
    end_line: 142
apis: []
---
