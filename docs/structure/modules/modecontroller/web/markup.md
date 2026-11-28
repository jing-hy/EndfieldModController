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
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.025Z"
fingerprint: 2e863f97265b5bf02074bfb159f438acdf43f8f0e4a0f1e68829ea4d03e25239
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1984
  - path: "frontend/src/styles/tokens.css"
    line: 200
    end_line: 588
apis:
  - protocol: file
    path: "web/index.html+style.css"
    description:
      zh: >
          没有导出函数：这个叶子就是页面骨架与共用样式，由各个渲染函数往里填。
          
      en: >
          No exported functions: this leaf is the page skeleton and shared styling the renderers fill in.
          
---
