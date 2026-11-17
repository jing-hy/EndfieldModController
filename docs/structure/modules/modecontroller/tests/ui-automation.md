---
uid: b1d0e504
id: modecontroller.tests.ui-automation
parent: modecontroller.tests
tags: [tests]
name: {zh: "自动化通道测试", en: "Automation Channel Tests"}
description:
  zh: >
      钉住无障碍通道的判据：只绑本机、token 校验、命令往返、前端不响应必须报超时、退出时删掉状态文件，以及前端那一半真的挂在 index 上。
      
  en: >
      Pins the channel's invariants: localhost-only, token check, command round-trip, honest timeout when the frontend is silent, state file removed on shutdown, and the frontend half really being wired in.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.133Z"
fingerprint: 2db17bb5839ca268dd89bb1a81ac4a6d87f688b301e10e07c32090272b6710d2
source:
  - path: "tests/test_ui_automation.py"
    line: 1
    end_line: 214
apis: []
---
