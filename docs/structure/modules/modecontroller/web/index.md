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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.333Z"
fingerprint: 83cda12b0aed97e5a4b3f723099f81a11589e8437a4c6c57bc34854751bc5978
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1208
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
