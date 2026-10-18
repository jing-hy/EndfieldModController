---
uid: b1c0a004
id: modecontroller.tests
parent: modecontroller
tags: [tests, quality]
name: {zh: "测试套件", en: "Test Suite"}
description:
  zh: >
      tests/ 下的离线单测（pytest，45 个文件 / 418 例）：全部把路径打到 tmp_path，不联网、不碰真实游戏目录与 runtime。覆盖库扫描布局、激活与依赖、Mod 库安全护栏、崩溃归因与记忆、诊断包、自更新、公告版本区间、ini 体检等。跑法 python -m pytest tests -q。
      
  en: >
      Offline unit tests under tests/ (pytest, 45 files / 418 cases): every path is patched to tmp_path — no network, no touching the real game dir or runtime. Covers library-scan layout, activation and dependencies, library-safety guards, crash attribution and memory, diagnostic bundles, self-update, alert version gating and ini linting. Run: python -m pytest tests -q.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.441Z"
fingerprint: 4cf4ae80cf0a41fd6249100104ac004e5d3b51c66dc789667675186a24294bb6
source:
  - path: "tests/test_activation.py"
  - path: "tests/test_crash_cause.py"
  - path: "tests/test_risk_memory.py"
---
