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
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.431Z"
fingerprint: 991ca6bc0312d7dbd6a6567572ef6f289323954a2fc2ad147f22179b98db4d48
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
