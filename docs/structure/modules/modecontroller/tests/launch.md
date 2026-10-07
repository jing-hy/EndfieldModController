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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.359Z"
fingerprint: 82f7160f989ccd0adccceca844e67a93c2e55e7dcb7c23ebd99c0a8728e57c10
source:
  - path: "tests/test_launcher_api.py"
    line: 1
    end_line: 286
  - path: "tests/test_hotkey_panel.py"
    line: 1
    end_line: 2757
  - path: "tests/test_controller_ini_lint.py"
    line: 1
    end_line: 66
  - path: "tests/test_e2e_offline.py"
    line: 1
    end_line: 140
apis: []
---
