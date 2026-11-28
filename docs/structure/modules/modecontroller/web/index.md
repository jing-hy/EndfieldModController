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
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.839Z"
fingerprint: b37401ee3e40d737fba14328ca3b242d2ca7aa64df05ea65fd7506b212e22168
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1984
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
