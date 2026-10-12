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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.884Z"
fingerprint: 93647e521ce347112293ca2b8ade78afe638a7f94cc8123435b754a9573fe7f3
source:
  - path: "endfieldmodcontroller/crashwatch.py"
  - path: "endfieldmodcontroller/diagnostics.py"
  - path: "endfieldmodcontroller/deviceinfo.py"
---
