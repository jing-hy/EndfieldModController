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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.287Z"
fingerprint: 428bf6dbbf7e86ffe32e5cadcd547e2b215e413350be964118034c77c3a69fa3
source:
  - path: "frontend/src/App.vue"
    line: 1
    end_line: 1606
  - path: "frontend/src/styles/tokens.css"
    line: 1
    end_line: 190
apis:
  - protocol: file
    path: "web/index.html+style.css"
    description:
      zh: >
          没有导出函数：这个叶子就是页面骨架与共用样式，由各个渲染函数往里填。
          
      en: >
          No exported functions: this leaf is the page skeleton and shared styling the renderers fill in.
          
---
