---
uid: b1d0f005
id: modecontroller.backend.observe.watch
parent: modecontroller.backend.observe
tags: [watch]
name: {zh: "崩溃监视器", en: "Crash Watcher"}
description:
  zh: >
      后台监视器：从启动盯到退出，其间采样，退出时收证据、写报告、打崩溃包，并判定这一次是“跑通了”还是“崩了”。
      
  en: >
      The background watcher: follow the game process from launch to exit, sample it meanwhile, and when it exits collect evidence, write the report, build the bundle and decide whether this run was a success or a crash.
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.754Z"
fingerprint: 9112e4a8695909130afe36250c9b5b986c41480fbad2baa07b8035ac11747cb4
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 3623
    end_line: 6041
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 3720
    end_line: 6110
apis:
  - protocol: rpc
    path: "start_watch"
    description:
      zh: >
          在后台线程里盯住游戏进程（等它出现、再等它退出，带超时）。
          
      en: >
          Start following the game process in a background thread (waits for it to appear, then to exit, with a timeout).
          
  - protocol: rpc
    path: "watch_state"
    description:
      zh: >
          监视器在跑吗、在等什么。
          
      en: >
          Is the watcher running, and what is it waiting on.
          
deps:
  - kind: call
    to: modecontroller.backend.observe.evidence
    label: {zh: "退出时收集", en: "Collects on exit"}
  - kind: call
    to: modecontroller.backend.observe.sample
    label: {zh: "其间做采样", en: "Samples meanwhile"}
---
