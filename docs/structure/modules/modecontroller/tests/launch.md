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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.935Z"
fingerprint: 40812b3198b350f8d65b915f9784178a99c4b43d4596a059689238761d395298
source:
  - path: "tests/test_launcher_api.py"
    line: 2
    end_line: 2078
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
    line: 115
apis: []
---
