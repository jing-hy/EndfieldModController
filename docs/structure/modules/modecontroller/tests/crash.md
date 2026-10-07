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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.274Z"
fingerprint: 3cbb38bb42b7f87ebcbd08e9886469624654eb16c23bd7730e6e3f3bcc84d8a6
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
