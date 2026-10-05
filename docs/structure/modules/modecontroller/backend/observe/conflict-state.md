---
uid: b1d0f00a
id: modecontroller.backend.observe.conflict-state
parent: modecontroller.backend.observe
tags: [state]
name: {zh: "冲突结论留痕", en: "Conflict Verdict State"}
description:
  zh: >
      把最近一次的静态冲突结论落盘，好让崩溃监视器（跑在另一线程、常常是下一次会话）仍能判断这次崩溃背后有没有已知冲突 —— 并保证结论绑定在“当时那批 staged Mod”上。
      
  en: >
      Persist the last static-conflict verdict so the crash watcher (running on another thread, often in a later session) can still tell whether this crash had a known conflict behind it — and keep the answer tied to the exact staged mod set it was computed for.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.314Z"
fingerprint: 0c53c8639adc28a15a835bab7ab846058eb0edaca5528357bc84a1ba597a42dc
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 1868
    end_line: 4014
apis:
  - protocol: rpc
    path: "record_mod_conflicts"
    description:
      zh: >
          把最近的静态冲突结论落盘，并**绑定在“当时那批 staged Mod”上**。
          
      en: >
          Persist the latest static-conflict verdict, bound to the exact staged mod set it was computed for.
          
  - protocol: rpc
    path: "mod_conflict_state"
    description:
      zh: >
          读回那份结论（没写过或已过期就返回空）。
          
      en: >
          Read that verdict back (empty when it was never written or has gone stale).
          
---
