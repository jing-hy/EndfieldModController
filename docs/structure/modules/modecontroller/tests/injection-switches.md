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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.278Z"
fingerprint: 6574d21b282ecd6bd243729fd72a297294e64d74193958da0b36702df0608ebf
source:
  - path: "tests/test_injection_switches.py"
    line: 910
    end_line: 2038
apis: []
---
