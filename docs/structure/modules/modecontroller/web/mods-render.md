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
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.301Z"
fingerprint: b68f0cf991f5d405cf269b18527062c0e0821dda964b558f65ae4834a6320c9a
source:
  - path: "frontend/src/pages/ModLibraryPage.vue"
    line: 2
    end_line: 1216
apis:
  - protocol: rpc
    path: "web.renderMods"
    description:
      zh: >
          画 Mod 库：按角色分组、跳过依赖、标出重复副本与置信度；卡片上那个黄色「未识别 · 点此选角色」/「类型待确认」标签就是这里画的（点了要真能弹出归类窗口）。
          
      en: >
          Draw the library: group character mods, skip dependencies, mark duplicates and confidence, plus the yellow "not recognised · click to pick a character" badge.
          
---
