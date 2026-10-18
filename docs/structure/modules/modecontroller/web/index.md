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
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.444Z"
fingerprint: 0e7871012c31c8dd07f93b75d8ec9f3923a4c1648c4a4bfbad45f027e51b1160
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1622
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
