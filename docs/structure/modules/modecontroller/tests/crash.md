---
uid: b1d15005
id: modecontroller.tests.crash
parent: modecontroller.tests
tags: [tests]
name: {zh: "崩溃与守护测试", en: "Crash & Watchdog Tests"}
description:
  zh: >
      崩溃侧的测试：判定规则（只有真的上传转储才算崩）、崩溃记忆（含“跑通就移出”那条新行为）、关键文件守护，以及设备信息报告。
      
  en: >
      Tests for the crash side: the verdict rules (only an uploaded dump counts), crash memory including the forget-on-success behaviour, the key-file watchdog, and device reporting.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.327Z"
fingerprint: 98c8157d8691c652f6488fcaf95b39720a968ba8e5e27a1554e9282ca1cee98a
source:
  - path: "tests/test_crash_cause.py"
    line: 1
    end_line: 294
  - path: "tests/test_risk_memory.py"
    line: 1
    end_line: 261
  - path: "tests/test_filewatch.py"
    line: 1
    end_line: 161
  - path: "tests/test_deviceinfo.py"
    line: 1
    end_line: 49
apis: []
---
