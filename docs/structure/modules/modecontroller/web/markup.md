---
uid: b1d13003
id: modecontroller.web.markup
parent: modecontroller.web
tags: [markup]
name: {zh: "页面骨架与样式", en: "Page Skeleton & Styles"}
description:
  zh: >
      页面骨架与样式（Vue）：侧边栏布局、顶栏，以及所有页面共用的设计令牌与主题变量。
      
  en: >
      Page skeleton and styling (Vue): the sidebar layout, the header, and the design tokens / theme variables shared by all pages.
      
revision: bf4fd078330843729d79451ed7aa1a080a39340a
updated_at: "2026-11-07T06:45:10.149Z"
fingerprint: 4a5eba4e88589ef1620a3172f19f9c17be4f632e38c275ed11807ab5689ab721
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1880
  - path: "frontend/src/styles/tokens.css"
    line: 227
    end_line: 642
apis:
  - protocol: file
    path: "web/index.html+style.css"
    description:
      zh: >
          没有导出函数：这个叶子就是页面骨架与共用样式，由各个渲染函数往里填。
          
      en: >
          No exported functions: this leaf is the page skeleton and shared styling the renderers fill in.
          
---
