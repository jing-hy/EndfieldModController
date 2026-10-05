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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.316Z"
fingerprint: 3fb420114abfd292c11af3fd53ecc5032baa6def0a6f6eb915c7cd237bf5a000
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1649
    end_line: 2093
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1746
    end_line: 2162
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
