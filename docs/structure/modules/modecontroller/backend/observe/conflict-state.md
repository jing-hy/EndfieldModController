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
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.749Z"
fingerprint: c99fabfabd18ca7547b5f7ce6c4541782472e1509413a1fae1dd9f4046f42ed3
source:
  - path: "endfieldmodcontroller/diagnostics.py"
    line: 4524
    end_line: 9326
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
