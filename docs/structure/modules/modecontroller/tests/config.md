---
uid: 4c8be1d8
id: modecontroller.tests.config
parent: modecontroller.tests
tags: [tests, config]
name: {zh: "配置测试", en: "Config Tests"}
description:
  zh: >
      配置与数据根的自愈回归：改名跟随、幂等、外部路径不被改写、旧根不被重建、留空回填、store_path 归一化，以及第一次安装乳摇时记相对路径。
      
  en: >
      Regression tests for config and data-root self-healing: follow a rename, stay idempotent, never rewrite external paths, never resurrect the old root, refill blanks, normalize stored paths, and record a relative tool dir on first install.
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.406Z"
fingerprint: a361d31a55d12472c7191cc8e018cb183829f8fd669830c8339d2753beec1dbd
source:
  - path: "tests/test_config_data_root_relocation.py"
apis:
  - protocol: rpc
    path: "tests.test_config_data_root_relocation"
    description:
      zh: >
          14 条配置/数据根自愈用例。
          
      en: >
          Fourteen config / data-root self-healing cases.
          
---
