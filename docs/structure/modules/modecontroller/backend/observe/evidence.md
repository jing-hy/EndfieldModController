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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.528Z"
fingerprint: 1f6266d1aca64db85ba254b5d330cbcb42f96ca5d851b23e2503ed0d3713ff92
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 83
    end_line: 128
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1878
    end_line: 4551
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 2505
    end_line: 4782
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
