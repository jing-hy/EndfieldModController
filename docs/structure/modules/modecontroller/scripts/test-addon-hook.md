---
uid: 7a3c1f24
id: modecontroller.scripts.test-addon-hook
parent: modecontroller.scripts
tags: [panel, test, tooling]
name: {zh: "面板注入自测入口", en: "Panel Injection Self-test Runner"}
description:
  zh: >
      编译假 EFMI 与宿主 exe（复用 `scripts.build-addon` 的 MSVC 定位）、带上 `MODECONTROLLER_HOOK_MODULE` 环境变量跑一遍，并把 21 条断言的输出原样打出来。退出码 0 = 全过、1 = 有用例失败、2 = 编译环境不可用。
      
  en: >
      Compile the fake EFMI and the host exe (reusing `scripts.build-addon`'s MSVC discovery), run it with `MODECONTROLLER_HOOK_MODULE` set, and print the 21 assertions verbatim. Exit code 0 = all pass, 1 = a case failed, 2 = no compiler available.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.539Z"
fingerprint: 26e5f6b8a5d100a920a1543aba2287478426c10d8402cf76bd85b1281774e3b7
source:
  - path: "scripts/test_addon_hook.py"
    line: 85
    end_line: 252
apis:
  - protocol: rpc
    path: "scripts.test_addon_hook"
    description:
      zh: >
          跑一遍注入链路自测（`python scripts\test_addon_hook.py`）。
          
      en: >
          Run the injection-link self-test (`python scripts\test_addon_hook.py`).
          
deps:
  - kind: call
    to: modecontroller.scripts.build-addon
    label: {zh: "复用它的 MSVC 定位", en: "Reuses its MSVC discovery"}
---
