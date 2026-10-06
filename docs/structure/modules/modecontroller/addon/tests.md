---
uid: 7a3c1f23
id: modecontroller.addon.tests
parent: modecontroller.addon
tags: [panel, native, test]
name: {zh: "面板注入离线自测", en: "Offline Injection Self-test"}
description:
  zh: >
      离线验证注入链路：造一个“假 EFMI”（**只通过导入表轮询 `GetAsyncKeyState`**，与真 EFMI 同一种读法）+ 一个宿主 exe，逐条断言 21 条——找模块、改导入表、注入被读到、跨帧保持、“刚按下”只出现一次、修饰键 + 主键组合、到点自动释放、**只影响目标模块**、未注入的键原样透传真实状态、**卸载时把导入表恢复原样**。
      
  en: >
      Offline verification of the injection link: a "fake EFMI" (**polling `GetAsyncKeyState` through its import table**, the way the real one reads keys) plus a host exe asserting 21 points: module found, import table patched, injection observed, held across frames, "just pressed" only once, modifier+key combo, automatic release, only the target module affected, untouched keys passed through, table restored on unload.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.951Z"
fingerprint: 2f31190229b81a272bb444aa4b47bbb00880b9d4c41a2948ed0d6387754ecbd2
source:
  - path: "reshade_addon/tests/hook_host.cpp"
    line: 116
    end_line: 345
  - path: "reshade_addon/tests/fake_efmi_d3d11.cpp"
    line: 24
    end_line: 69
apis:
  - protocol: rpc
    path: "FakeFrameRead"
    description:
      zh: >
          假 EFMI 的"读一帧"：返回 `0x8000`（正按住）与 `0x0001`（刚按下）两个位。
          
      en: >
          The fake EFMI's "read one frame": returns the `0x8000` (held) and `0x0001` (just pressed) bits.
          
  - protocol: rpc
    path: "hook_host.exe"
    description:
      zh: >
          自测宿主：加载假 EFMI、装 hook、注入按键、逐条断言并打印 `[PASS]/[FAIL]`，全过才退出码 0。
          
      en: >
          Self-test host: loads the fake EFMI, installs the hook, injects keys, asserts every point and prints `[PASS]/[FAIL]`; exits 0 only if all pass.
          
---
