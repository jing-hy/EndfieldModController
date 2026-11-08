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
      
revision: 98e1fd157ee785be02b700a7086f9d8f77b037de
updated_at: "2026-11-08T02:13:35.849Z"
fingerprint: 6c538c2a63c3c16b36c78bcac0c3c8bb36658166c001a1eba81392af6055dee0
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1880
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
