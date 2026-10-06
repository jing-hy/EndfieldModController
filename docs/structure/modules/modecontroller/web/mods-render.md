---
uid: b1d13005
id: modecontroller.web.mods-render
parent: modecontroller.web
tags: [render]
name: {zh: "库渲染", en: "Library Rendering"}
description:
  zh: >
      Mod 库页（Vue）：三个分区卡片 —— 皮肤 Mod 开关 / 下载 Mod / Mod 列表；按 conflict_group 分组渲染卡片、勾选与同角色互斥、封面懒加载、冲突处理弹窗。
      
  en: >
      Mod library page (Vue): skin-mod toggles, URL download card, and the grouped mod list with selection, mutual exclusion, lazy covers and the conflict dialog.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:01.010Z"
fingerprint: 32825ea5d79718c2272aff934aaa7bbc47cf0630e765e7f3b5eae4b030a27408
source:
  - path: "frontend/src/pages/ModLibraryPage.vue"
    line: 1
    end_line: 1050
apis:
  - protocol: rpc
    path: "web.renderMods"
    description:
      zh: >
          画 Mod 库：按角色分组、跳过依赖、标出重复副本与置信度；卡片上那个黄色「未识别 · 点此选角色」/「类型待确认」标签就是这里画的（点了要真能弹出归类窗口）。
          
      en: >
          Draw the library: group character mods, skip dependencies, mark duplicates and confidence, plus the yellow "not recognised · click to pick a character" badge.
          
---
