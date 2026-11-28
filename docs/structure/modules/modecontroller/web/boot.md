---
uid: b1d1300e
id: modecontroller.web.boot
parent: modecontroller.web
tags: [boot]
name: {zh: "启动与绑定", en: "Boot & Bindings"}
description:
  zh: >
      前端入口（Vue）：main.js 挂载 + index.html 的 head 内联主题（防止首屏闪默认色）。
      
  en: >
      Frontend entry: main.js mount plus the inline theme script in index.html (prevents a flash of the default colour).
      
revision: b124e58720a8b882c922f28505d3d1412c494693
updated_at: "2026-11-28T17:22:47.854Z"
fingerprint: 188f6837c09e8073f36bf40ab7ef7237e82911a58568df89a17b6716c3056f6e
source:
  - path: "frontend/index.html"
    line: 1
    end_line: 48
apis:
  - protocol: rpc
    path: "web.boot"
    description:
      zh: >
          开机：加载页至少停留一小段、先让出一次绘制、拉状态，再决定该弹哪些窗。
          
      en: >
          Startup: keep the splash up for a minimum, yield one paint, load state, then decide which popups are due.
          
  - protocol: rpc
    path: "web.bind"
    description:
      zh: >
          接好所有按钮、输入与全局事件。
          
      en: >
          Wire every button, input and global handler.
          
  - protocol: rpc
    path: "web.splashMsg"
    description:
      zh: >
          更新加载页文案 / 淡出它。
          
      en: >
          Update the splash text / fade it out.
          
---
