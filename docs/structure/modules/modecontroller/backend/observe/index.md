---
uid: b1c0b00a
id: modecontroller.backend.observe
parent: modecontroller.backend
tags: [crash, diagnostics]
name: {zh: "崩溃监控与诊断", en: "Crash Watch & Diagnostics"}
description:
  zh: >
      看清到底发生了什么：盯游戏进程并每几秒采样，收崩溃证据（CrashSight 标记、Player.log、模块列表、事件日志），判定崩因，打崩溃包/诊断包，维护「哪套 Mod 组合崩过」的记忆，并报告设备与显卡事实。
      
  en: >
      Seeing what actually happened: watch the game process and sample it every few seconds, collect crash evidence (CrashSight markers, Player.log, module list, event log), classify the cause, build crash/diagnostic bundles, keep a crash memory of mod combinations, and report device/GPU facts.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.249Z"
fingerprint: bfb46fa5dc798dce0c33f6f6ac47e5175aa13de6c80598007c5b538fa7a76f31
source:
  - path: "endfieldmodcontroller/crashwatch.py"
  - path: "endfieldmodcontroller/diagnostics.py"
  - path: "endfieldmodcontroller/deviceinfo.py"
---
