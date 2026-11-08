---
uid: b1d0c002
id: modecontroller.backend.api.mods
parent: modecontroller.backend.api
tags: [api, mods]
name: {zh: "Mod 库操作", en: "Library Operations"}
description:
  zh: >
      从界面浏览与编辑库：重扫、取封面图、看详情、改角色归属或类型、移出库，以及列出已知角色与还在等确认的 Mod。
      
  en: >
      Browse and edit the library from the UI: rescan, fetch a mod's cover image, show its detail sheet, reassign its character or kind, remove it from the library, and list the characters the program knows plus those still waiting for confirmation.
      
revision: 98e1fd157ee785be02b700a7086f9d8f77b037de
updated_at: "2026-11-08T02:13:35.797Z"
fingerprint: e9b880b3f1d50cf0ee5ac737b642b283af5e5ab2b9a0ae0643578d00b5eb1524
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2860
    end_line: 6917
  - path: "endfieldmodcontroller/api.py"
    line: 4874
    end_line: 15744
apis:
  - protocol: rpc
    path: "scan"
    description:
      zh: >
          重扫库并返回当前页签要的 Mod 列表。
          
      en: >
          Rescan the library and return the mod list for the current tab.
          
  - protocol: rpc
    path: "get_mod_cover"
    description:
      zh: >
          把某个 Mod 的封面图给卡片。
          
      en: >
          Serve a mod's cover image to the card.
          
  - protocol: rpc
    path: "mod_more_info"
    description:
      zh: >
          单个 Mod 的详情（路径、动作、修复状态、能否回滚）。
          
      en: >
          Detail sheet for one mod (paths, actions, fix state, rollback availability).
          
  - protocol: rpc
    path: "set_mod_character"
    description:
      zh: >
          改一个 Mod 的角色归属（写它的 meta 侧车文件）。
          
      en: >
          Reassign a mod's character (writes its meta sidecar).
          
  - protocol: rpc
    path: "set_mod_kind"
    description:
      zh: >
          在角色 Mod 与辅助 Mod 之间切换。
          
      en: >
          Flip a mod between character and assist.
          
  - protocol: rpc
    path: "delete_mod"
    description:
      zh: >
          把一个 Mod 移出库 —— **唯一**允许动库的入口（移进回收目录，可找回）。
          
      en: >
          Remove a mod from the library — the only path allowed to delete from it (moves to trash, recoverable).
          
---
