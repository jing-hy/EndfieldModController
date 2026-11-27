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
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.297Z"
fingerprint: b050a91a0b71ec0ff4ce407a7660d313692f86951945443746f13632b0bef63b
source:
  - path: "tests/test_ui_automation.py"
    line: 215
    end_line: 642
apis: []
---
