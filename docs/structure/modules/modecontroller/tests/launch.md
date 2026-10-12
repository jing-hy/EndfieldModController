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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.903Z"
fingerprint: f024f5418310bc23ad4ba991c2a32cfb85821206a7306126f58310f56902f3bb
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
