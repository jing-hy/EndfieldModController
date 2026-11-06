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
      
revision: 6956df017aaf625c5a15ea64c5d6f1d0f5ac2bd4
updated_at: "2026-11-06T13:05:30.487Z"
fingerprint: 6c538c2a63c3c16b36c78bcac0c3c8bb36658166c001a1eba81392af6055dee0
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1826
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
