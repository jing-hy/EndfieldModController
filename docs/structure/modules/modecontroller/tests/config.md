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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.357Z"
fingerprint: 51949bfa395f0baca618f24629e9844d1913e1a13c81328f36ca26b4c555f9e7
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
