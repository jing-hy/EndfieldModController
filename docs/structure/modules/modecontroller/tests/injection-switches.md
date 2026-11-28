---
uid: b1d1ab01
id: modecontroller.tests.injection-switches
parent: modecontroller.tests
tags: [tests]
name: {zh: "注入开关测试", en: "Injection Switch Tests"}
description:
  zh: >
      注入开关的落配置回归（2026-10-03 的「乳摇 / Poser 关不掉」）：动作成功 ⇒ 配置跟着变且落盘；失败且没动手 ⇒ 一个字不改并给出人话原因；关掉之后启动自检不许再装回来。
      
  en: >
      Regression for the injection switches that toggle real install/uninstall state: a successful action must write the switch back into the config, a failure that did nothing must leave the config untouched and explain why, and the launch self-check must not reinstall what the user turned off.
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.020Z"
fingerprint: ce911df192bf61c9f3a65abbb7c7cb77957144f1a7d2898abbc39fcf21add2f5
source:
  - path: "tests/test_injection_switches.py"
    line: 911
    end_line: 2040
apis: []
---
