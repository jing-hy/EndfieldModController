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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.286Z"
fingerprint: df9c5be8364d65f284fec6de907008b1d43d07019626d75d370712a579af49da
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1606
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
