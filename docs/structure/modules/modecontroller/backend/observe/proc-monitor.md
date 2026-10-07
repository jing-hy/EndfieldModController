---
uid: b1d0f009
id: modecontroller.backend.observe.proc-monitor
parent: modecontroller.backend.observe
tags: [process]
name: {zh: "子进程监视", en: "Child Process Monitor"}
description:
  zh: >
      盯住拉起来的进程，别让一次“静默失败”被丢掉：轮询它、截住输出尾部，退出时记下退出码与死亡现场 —— 辅助进程崩了不会就这么消失。
      
  en: >
      Watch a launched process so a quiet failure is not lost: poll it, capture its output tail, and on exit record the code and a post-mortem line — the reason a crashed helper does not just vanish.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.349Z"
fingerprint: f1d18d8ea615542c25a81e2399fd65acfa3a9f44da7ef9a1d362549c5453fbea
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 383
    end_line: 8562
apis:
  - protocol: rpc
    path: "start_process_monitor"
    description:
      zh: >
          盯住拉起的辅助进程，别让“静默失败”被丢掉（记退出码与输出尾部）。
          
      en: >
          Watch a spawned helper so a quiet failure is not lost (exit code + output tail captured).
          
---
