---
uid: b1d13006
id: modecontroller.web.mods-menu
parent: modecontroller.web
tags: [actions]
name: {zh: "单 Mod 操作", en: "Per-Mod Actions"}
description:
  zh: >
      Mod 卡片「⋯」就地面板（Vue）：更换归属 / 修复 / 回滚 / 打开目录 / 移出库；移出库带确认框并说明可找回位置。 动作总入口 `menuAct(act, mod)` 同时服务两个入口：⋯ 菜单与卡片上的黄色标签，且本地异常不再被空 catch 吞掉。⚠️ “点了没反应”的**真因是 `<CharacterAssignDialog>` 没 import**（Vue 当未知元素 ⇒ 弹窗不渲染 + ref 拿到 DOM 元素 ⇒ `openFor is not a function`），现由 `tests/test_frontend_components.py` 钉住。
      
  en: >
      Per-mod overflow menu (Vue): reassign character, fix, rollback, open folder, remove from library. The dispatcher accepts the mod either from the overflow menu or directly from the card's badge, and never swallows a local error silently. The assign dialog must be imported: an unresolved tag renders nothing and hands the code a DOM element.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.334Z"
fingerprint: 63221a5a3a09dc421eda5b3fefc6da091153baee522ff41d48a0fc48614574db
source:
  - path: "frontend/src/pages/ModLibraryPage.vue"
    line: 1
    end_line: 658
apis:
  - protocol: rpc
    path: "web.openModMenu"
    description:
      zh: >
          单个 Mod 的**就地菜单**（不是弹窗）：带状态行、不可用项置灰、碰到窗口边缘会自动改向。
          
      en: >
          The in-place per-mod menu (not a modal): status line, greyed-out unavailable items, edge-aware placement.
          
  - protocol: rpc
    path: "web.doFixMod"
    description:
      zh: >
          修复一个 Mod（破坏性动作，先弹确认）。
          
      en: >
          Repair one mod (with a destructive-action confirmation first).
          
  - protocol: rpc
    path: "web.doRollbackMod"
    description:
      zh: >
          把修过的 Mod 回滚。
          
      en: >
          Roll a repaired mod back.
          
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
          
  - protocol: rpc
    path: "web.menuAct"
    description:
      zh: >
          单 Mod 操作的总入口：先看传进来的那条 Mod（卡片标签路径），再看浮层里的 menu；本地异常不得静默吞掉。
          
      en: >
          The single dispatcher for the per-mod menu: it looks up the mod from the argument first (card badge path) and the open menu second, and never swallows a local error silently.
          
deps:
  - kind: call
    to: modecontroller.backend.api.mods
    label: {zh: "调 Mod 操作", en: "Calls mod actions"}
---
