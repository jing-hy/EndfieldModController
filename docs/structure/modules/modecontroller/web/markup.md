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
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.841Z"
fingerprint: a14c7eedb62a750428c7ed57ccfb68a4a71a69db37bbcc2663bd7f1757f409b2
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
