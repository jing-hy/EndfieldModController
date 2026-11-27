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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.095Z"
fingerprint: d351aa48370305d0140868566027abb4ae2bd4ce3330beaf8389955287bf7184
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 516
    end_line: 8908
apis:
  - protocol: rpc
    path: "start_process_monitor"
    description:
      zh: >
          盯住拉起的辅助进程，别让“静默失败”被丢掉（记退出码与输出尾部）。
          
      en: >
          Watch a spawned helper so a quiet failure is not lost (exit code + output tail captured).
          
---
