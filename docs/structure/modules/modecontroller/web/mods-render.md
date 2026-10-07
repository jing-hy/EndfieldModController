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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.549Z"
fingerprint: bd2fc7385caddad4ad61e5dc65d0937b3a16f8fe28d5c170753b740a0b9dba80
source:
  - path: "frontend/src/pages/ModLibraryPage.vue"
    line: 1
    end_line: 1072
apis:
  - protocol: rpc
    path: "web.renderMods"
    description:
      zh: >
          画 Mod 库：按角色分组、跳过依赖、标出重复副本与置信度；卡片上那个黄色「未识别 · 点此选角色」/「类型待确认」标签就是这里画的（点了要真能弹出归类窗口）。
          
      en: >
          Draw the library: group character mods, skip dependencies, mark duplicates and confidence, plus the yellow "not recognised · click to pick a character" badge.
          
---
