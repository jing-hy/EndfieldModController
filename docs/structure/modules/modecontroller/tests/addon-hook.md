---
uid: 7a3c1f25
id: modecontroller.tests.addon-hook
parent: modecontroller.tests
tags: [panel, test]
name: {zh: "注入链路回归测试", en: "Injection Link Regression"}
description:
  zh: >
      注入链路的 pytest 外壳：跑 `scripts.test-addon-hook` 并断言输出里有"0 项失败"；**编译器不在就 skip**（不让一台没装 MSVC 的机器把整个套件弄红）。这条链路一旦坏掉（例如某版 Windows 改了导入表形态，或有人把 `press` 的窗口语义改成"每帧都置低位"导致 toggle 连跳），它会立刻变红。
      
  en: >
      The pytest shell for the injection link: runs `scripts.test-addon-hook` and asserts the output says "0 failures"; it **skips when no compiler is present** (a machine without MSVC must not turn the whole suite red). If this link breaks — e.g. a Windows version changes the import-table shape, or `press` starts setting the low bit every frame — this test goes red.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.356Z"
fingerprint: cf3d9ac9c786927d350bc572a84109a5530104c9fd8e9aebb6b6ef9b58fb0476
source:
  - path: "tests/test_addon_hook.py"
    line: 43
    end_line: 126
apis:
  - protocol: rpc
    path: "AddonHookTests.test_key_injection_link"
    description:
      zh: >
          跑一次离线自测；编译器不可用（退出码 2）时 skip。
          
      en: >
          Run the offline self-test once; skip when the compiler is unavailable (exit code 2).
          
deps:
  - kind: call
    to: modecontroller.scripts.test-addon-hook
    label: {zh: "跑离线自测", en: "Runs the offline self-test"}
---
