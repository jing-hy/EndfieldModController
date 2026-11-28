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
      
revision: c5e7502f33b821a8fbb9f32403d00f1d3540841b
updated_at: "2026-11-28T10:16:58.092Z"
fingerprint: 518927801cbd3245ddd89278a488a10fa2a7d4b3131547488d0d8c1adac05c59
source:
  - path: "endfieldmodcontroller/activation.py"
deps:
  - kind: call
    to: modecontroller.backend.library
    label: {zh: "读 Mod 并写产物", en: "Reads mods, writes artifacts"}
---
