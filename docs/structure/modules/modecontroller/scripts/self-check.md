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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.108Z"
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
