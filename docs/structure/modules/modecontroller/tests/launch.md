---
uid: b1d15003
id: modecontroller.tests.launch
parent: modecontroller.tests
tags: [tests]
name: {zh: "启动与面板测试", en: "Launch & Panel Tests"}
description:
  zh: >
      启动路径的测试：界面调用的那层 api、生成出来的 controller.ini 体检、统一热键面板协议、一次离线端到端跑，以及「首屏绝不发网络请求」（首屏只读更新缓存、联网交给后台预热 —— 2026-11-05 用户报「启动慢、加载页很久」的那条）。启动期的回归在用户之前就被它拦住。
      
  en: >
      Tests for the launch path: the api surface the UI calls, linting the generated controller ini, the unified hotkey panel protocol, one offline end-to-end run, and 'the first screen never hits the network' (it reads the update cache and lets background warm-up fetch — the 2026-11-05 slow-start fix). The suite that would catch a launch-time regression before a user does.
      
revision: 6956df017aaf625c5a15ea64c5d6f1d0f5ac2bd4
updated_at: "2026-11-06T13:05:30.482Z"
fingerprint: 93a8ea5959b3f8f9596fd0986710ddb7b0f36ffba754fa3af00fc9f0f0073ac1
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
  - path: "tests/test_startup_no_network.py"
    line: 1
apis: []
---
