---
uid: b1c0b004
id: modecontroller.backend.activation
parent: modecontroller.backend
tags: [staging]
name: {zh: "激活与中转", en: "Activation & Staging"}
description:
  zh: >
      把「勾选」变成「游戏真正加载的东西」：解同角色互斥与按需依赖，决定每份依赖用哪一份，把选中的 Mod 拷进 EFMI 的 Mods 中转区、处理热键、写控制器产物、收编手动放进来的 Mod，并在中转目录与用户库重叠时直接拒绝执行。
      
  en: >
      Turning a selection into what the game actually loads: resolve same-character exclusivity and on-demand dependencies, plan which copy of each dependency wins, copy selected mods into the EFMI Mods staging area, patch hotkeys, write controller artifacts, adopt hand-placed mods, and refuse to run whenever staging would overlap the user's library.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.293Z"
fingerprint: 36b80ba47e779dacffd640523cdba8db99d995903dae115ca0d68e471c71d1f2
source:
  - path: "endfieldmodcontroller/activation.py"
deps:
  - kind: call
    to: modecontroller.backend.library
    label: {zh: "读 Mod 并写产物", en: "Reads mods, writes artifacts"}
---
