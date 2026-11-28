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
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.024Z"
fingerprint: 57fc747e85837e9ed618d40b47e6f87d4a63f98e527952e590d5191d927d1809
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1984
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
