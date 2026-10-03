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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.330Z"
fingerprint: 527f0cc959b7f609675d215a7b018979ea9f63674bb2a4a40f50ed7db6d46572
source:
  - path: "tests/test_launcher_api.py"
    line: 1
    end_line: 286
  - path: "tests/test_hotkey_panel.py"
    line: 1
    end_line: 2745
  - path: "tests/test_controller_ini_lint.py"
    line: 1
    end_line: 66
  - path: "tests/test_e2e_offline.py"
    line: 1
    end_line: 140
apis: []
---
