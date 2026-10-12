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
      
revision: 55d938448b4178c517e948237ce04bb8fda54fbe
updated_at: "2026-10-12T14:48:34.249Z"
fingerprint: c461d3d4a36f7a4a8216b63daf23f7c72038e972c916b134608d0d1f0ea436ec
source:
  - path: "scripts/test_addon_hook.py"
    line: 104
    end_line: 290
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
