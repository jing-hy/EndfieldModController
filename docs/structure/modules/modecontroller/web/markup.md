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
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.999Z"
fingerprint: 908796136a83e3cf9b286179bebe41f4ba4b3ff01dd0d42761db09326e3ed46b
source:
  - path: "frontend/src/App.vue"
    line: 2
    end_line: 1622
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
