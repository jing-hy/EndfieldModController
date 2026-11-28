---
uid: b1d1400c
id: modecontroller.scripts.self-check
parent: modecontroller.scripts
tags: [check]
name: {zh: "导入自检", en: "Import Self-Check"}
description:
  zh: >
      给开发检出一个快速体检：依次 import 包内每个模块，让导入期错误在变成“打包后才发作的怪事”之前就被抓住。
      
  en: >
      A quick health probe for the development checkout: import every package module in turn so an import-time error is caught before it becomes a frozen-exe mystery.
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.903Z"
fingerprint: 03c382191f5be6d77ebdbbd6282ce27d9f9dacbc426a93a227ee9cc5c6fd128d
source:
  - path: "scripts/self_check.py"
    line: 2
    end_line: 90
apis:
  - protocol: rpc
    path: "scripts.self_check"
    description:
      zh: >
          依次 import 包内每个模块，让导入期错误在这里就暴露，而不是变成“打包后才发作的怪事”。
          
      en: >
          Import every package module in turn, so an import-time error surfaces here instead of as a frozen-exe mystery.
          
---
