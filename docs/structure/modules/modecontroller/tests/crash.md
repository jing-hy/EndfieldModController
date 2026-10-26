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
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.406Z"
fingerprint: 6b72362ed498d97cb509184c47ed307b5f070972ed672da43da697f0f007e94d
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
