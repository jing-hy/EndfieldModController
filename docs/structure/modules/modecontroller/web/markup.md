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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.941Z"
fingerprint: b934ee53fccb6d8e0a36341fc7f3a4227492410f2f536fd3e1745acaf0a62538
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
