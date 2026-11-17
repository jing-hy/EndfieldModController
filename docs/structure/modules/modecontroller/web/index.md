---
uid: b1c0a002
id: modecontroller.web
parent: modecontroller
tags: [frontend, ui]
name: {zh: "前端界面", en: "Web UI"}
description:
  zh: >
      前端根（Vue）：App.vue 负责侧边栏布局、页签切换、公告条、首启弹窗、拖放宿主与全局弹窗/提示宿主。
      
  en: >
      Frontend root (Vue): App.vue holds the sidebar layout, tab switching, notices, first-run dialog, drag-drop host and the global dialog/toast hosts.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.135Z"
fingerprint: 6649ba415e860f4010ee42f350cb13ba1e9a18931ac0c26c85564a1eff0e1b82
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1904
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
