---
uid: b1d1200a
id: modecontroller.backend.shell.cli
parent: modecontroller.backend.shell
tags: [cli]
name: {zh: "无界面入口", en: "Headless CLI"}
description:
  zh: >
      给脚本与冒烟测试用的无界面入口：构造配置、跑那些本来在界面背后的功能，把结果打成文本输出，而不开窗口。
      
  en: >
      A headless entry for scripts and smoke tests: build the config, run the pieces that live behind the UI, and print the result as text instead of opening a window.
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.919Z"
fingerprint: 465e23ad6dd5883b4049bd377cfa04797da6b6c70a17c7ecd5a672929fc6f74d
source:
  - path: "endfieldmodcontroller/cli.py"
    line: 16
    end_line: 62
apis:
  - protocol: rpc
    path: "cli.main"
    description:
      zh: >
          给脚本与冒烟测试的无界面入口（打文本、不开窗口）。
          
      en: >
          Headless entry for scripts and smoke tests (prints instead of opening a window).
          
---
