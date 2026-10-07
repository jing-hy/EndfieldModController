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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.548Z"
fingerprint: 7ec6b00bbb55cc05271f45988f609d68ba3d4eac9f95308e6b3e8573cb09e590
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1540
deps:
  - kind: call
    to: modecontroller.backend
    label: {zh: "调用后端 js_api", en: "Calls backend js_api"}
---
