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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.315Z"
fingerprint: 4329672076e8112f6390e2f811c0bee012c114e0d25954f0607b8a118480254a
source:
  - path: "endfieldmodcontroller/crashwatch.py"
  - path: "endfieldmodcontroller/diagnostics.py"
  - path: "endfieldmodcontroller/deviceinfo.py"
---
