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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.316Z"
fingerprint: 0c53c8639adc28a15a835bab7ab846058eb0edaca5528357bc84a1ba597a42dc
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 357
    end_line: 543
apis:
  - protocol: rpc
    path: "start_process_monitor"
    description:
      zh: >
          盯住拉起的辅助进程，别让“静默失败”被丢掉（记退出码与输出尾部）。
          
      en: >
          Watch a spawned helper so a quiet failure is not lost (exit code + output tail captured).
          
---
