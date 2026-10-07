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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.529Z"
fingerprint: 740da06dd55b03a09cff30988d47ec6aeec9d72e64f978fb669574af07fa387c
source:
  - path: "endfieldmodcontroller/crashwatch.py"
  - path: "endfieldmodcontroller/diagnostics.py"
  - path: "endfieldmodcontroller/deviceinfo.py"
---
