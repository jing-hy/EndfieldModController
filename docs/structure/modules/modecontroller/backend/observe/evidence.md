---
uid: b1d0f001
id: modecontroller.backend.observe.evidence
parent: modecontroller.backend.observe
tags: [evidence]
name: {zh: "证据收集", en: "Evidence Collection"}
description:
  zh: >
      收集判定所需的一切证据：注入快照（哪个 dll 在哪）、CrashSight 标记（分成 reportException 与 uploadCrash）、Player.log 尾部、正常退出标记，以及游戏自己报的错行。
      
  en: >
      Gather the evidence a crash verdict rests on: the injection snapshot (which dlls sit where), CrashSight markers split into reportException vs uploadCrash, the Player.log tail, the normal-exit marker, and the game's own error lines.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.315Z"
fingerprint: 3fb420114abfd292c11af3fd53ecc5032baa6def0a6f6eb915c7cd237bf5a000
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 82
    end_line: 126
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 613
    end_line: 786
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 779
    end_line: 837
apis:
  - protocol: rpc
    path: "collect_evidence"
    description:
      zh: >
          收集判定所需的一切：注入快照、CrashSight 标记、Player.log 尾部、正常退出标记、游戏报错行。
          
      en: >
          Collect everything a verdict rests on: injection snapshot, CrashSight markers, Player.log tail, normal-exit marker, game error lines.
          
  - protocol: rpc
    path: "injection_snapshot"
    description:
      zh: >
          记录捕获那一刻“哪个 dll 在哪”（游戏目录 + 注入库）。
          
      en: >
          Snapshot which dlls sit where (game folder + injection library) at the moment of capture.
          
---
