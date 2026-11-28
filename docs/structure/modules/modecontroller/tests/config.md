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
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.813Z"
fingerprint: a22e76d0d82ab82238f6bae8be5072ffc46540ff4eb45a60f4dac34c81377c73
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
