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
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.834Z"
fingerprint: ab8263f27f44256ecfefbb65ebaf63287d29a4a165e850a5793c3d7eb19474b4
source:
  - path: "tests/test_crash_cause.py"
    line: 2
    end_line: 296
  - path: "tests/test_risk_memory.py"
    line: 2
    end_line: 263
  - path: "tests/test_filewatch.py"
    line: 2
    end_line: 163
  - path: "tests/test_deviceinfo.py"
    line: 2
    end_line: 51
apis: []
---
