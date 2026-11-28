---
uid: b1d13006
id: modecontroller.web.mods-menu
parent: modecontroller.web
tags: [actions]
name: {zh: "单 Mod 操作", en: "Per-Mod Actions"}
description:
  zh: >
      Mod 卡片「⋯」就地面板（Vue）：更改所属角色 / 移到辅助或服装 / 打开目录 / 重命名 / 换预览图 / 移出库 / 彻底删除；移出库带确认框并说明可找回位置。2026-11-27 起「修复 Mod 文件」「回滚」两项已随功能移除。 动作总入口 `menuAct(act, mod)` 同时服务两个入口：⋯ 菜单与卡片上的黄色标签，且本地异常不再被空 catch 吞掉。⚠️ “点了没反应”的**真因是 `<CharacterAssignDialog>` 没 import**（Vue 当未知元素 ⇒ 弹窗不渲染 + ref 拿到 DOM 元素 ⇒ `openFor is not a function`），现由 `tests/test_frontend_components.py` 钉住。
      
  en: >
      Per-mod overflow menu (Vue): reassign character, move to assist/skin, open folder, rename, change cover, remove from library, permanently delete. The fix/rollback items were removed along with that feature on 2026-11-27. The dispatcher accepts the mod either from the overflow menu or directly from the card's badge, and never swallows a local error silently. The assign dialog must be imported: an unresolved tag renders nothing and hands the code a DOM element.
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.921Z"
fingerprint: c8fedc882923dbaf5157e78acaddf4564ec07fb6527cf1d08e22f3c2b78a90e1
source:
  - path: "frontend/src/pages/ModLibraryPage.vue"
    line: 2
    end_line: 1216
apis:
  - protocol: rpc
    path: "web.openModMenu"
    description:
      zh: >
          单个 Mod 的**就地菜单**（不是弹窗）：碰到窗口边缘会自动改向。
          
      en: >
          The in-place per-mod menu (not a modal): edge-aware placement.
          
  - protocol: rpc
    path: "web.doDeleteMod"
    description:
      zh: >
          把一个 Mod 移出库（界面上唯一允许这么做的入口）。
          
      en: >
          Remove a mod from the library (the only UI path allowed to do so).
          
  - protocol: rpc
    path: "web.openCharacterAssign"
    description:
      zh: >
          改一个 Mod 的角色归属 —— ⋯ 菜单和卡片上的黄色标签**两个入口**都能到。
          
      en: >
          Reassign which character a mod belongs to — reachable both from the overflow menu and from the card's yellow badge.
          
deps:
  - kind: call
    to: modecontroller.backend.api.mods
    label: {zh: "调 Mod 操作", en: "Calls mod actions"}
---
