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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.355Z"
fingerprint: a63390a86a82bb31ee43e1d909304617b0fdd8410e8b9f8663fbb388256b5d12
source:
  - path: "scripts/self_check.py"
    line: 1
    end_line: 88
apis:
  - protocol: rpc
    path: "scripts.self_check"
    description:
      zh: >
          依次 import 包内每个模块，让导入期错误在这里就暴露，而不是变成“打包后才发作的怪事”。
          
      en: >
          Import every package module in turn, so an import-time error surfaces here instead of as a frozen-exe mystery.
          
---
