---
uid: b1d12004
id: modecontroller.backend.data.ini-lint
parent: modecontroller.backend.data
tags: [lint]
name: {zh: "ini 体检", en: "Ini Linter"}
description:
  zh: >
      按 3DMigoto 自己的源码规则体检生成的 ini，找出会被**静默跳过**的行：非法/重名的 [Constants]、赋给未声明变量的行、`run` 目标不存在的键 —— **再加上**（2026-10-02）跨命名空间引用里的大写字母：3DMigoto 按小写登记变量名，写大写会让那行被悄悄丢掉。
      
  en: >
      Health-check generated inis against 3DMigoto's own source rules to find lines that get silently skipped: illegal/redeclared Constants, assignments to undeclared variables, keys whose `run` target is missing — **plus** (2026-10-02) uppercased cross-namespace references, which 3DMigoto drops silently because it registers variables in lowercase.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.963Z"
fingerprint: 602f0cae8de7d17ce78618326f399835351802b24b4a6cd51ac2507541cae40c
source:
  - path: "endfieldmodcontroller/ini_lint.py"
    line: 115
    end_line: 561
  - path: "endfieldmodcontroller/ini_lint.py"
    line: 356
    end_line: 580
apis:
  - protocol: rpc
    path: "ini_lint.lint_text"
    description:
      zh: >
          体检一份 ini 文本，返回“会被 3DMigoto 静默跳过”的行清单。
          
      en: >
          Lint one ini text; returns the list of lines 3DMigoto would silently skip.
          
---
