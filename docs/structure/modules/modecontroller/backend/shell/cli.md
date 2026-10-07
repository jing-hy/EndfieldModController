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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.533Z"
fingerprint: 0914c1e43cd040b881871dfefcaf6de48426bd355ec5a24fbdded0eb5a6dd900
source:
  - path: "endfieldmodcontroller/cli.py"
    line: 15
    end_line: 60
apis:
  - protocol: rpc
    path: "cli.main"
    description:
      zh: >
          给脚本与冒烟测试的无界面入口（打文本、不开窗口）。
          
      en: >
          Headless entry for scripts and smoke tests (prints instead of opening a window).
          
---
