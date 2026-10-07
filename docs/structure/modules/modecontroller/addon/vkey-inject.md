---
uid: 7a3c1f22
id: modecontroller.addon.vkey-inject
parent: modecontroller.addon
tags: [panel, native, input]
name: {zh: "进程内按键注入", en: "In-Process Key Injection"}
description:
  zh: >
      不经 Windows 输入队列的按键注入：找 EFMI 的 `d3d11.dll` → 遍历它的**导入表**把 `GetAsyncKeyState` 换成我们的函数（**只改数据、不碰代码段**；同名模块逐个试，谁真的导入它就接谁）→ 点按钮时把该键标成“按下 180 毫秒”，EFMI 下一帧轮询就读到了，窗口一到自动放开。窗口内**第一帧给 `0x8001`、之后只给 `0x8000`**（两种常见读法都只触发一次）；真修饰键状态原样透传；**卸载时把导入表恢复原样**（否则 addon 被卸载后 EFMI 会跳进已卸载的代码）。
      
  en: >
      Key injection that bypasses the Windows input queue: find EFMI's `d3d11.dll` → walk its **import table** and swap `GetAsyncKeyState` for our function (data only, no code patching; candidates are tried until one really imports that call) → a click marks that key as held for 180 ms, EFMI's next poll sees it and it releases itself. First read returns `0x8001`, later ones `0x8000`, so both polling styles fire once. Unload restores the table.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.504Z"
fingerprint: eb14a612c3cf14e1ee23ef3bbfb35cba33d9c9041ce287653ee5367aa8f93e13
source:
  - path: "reshade_addon/src/vkey_inject.h"
    line: 436
    end_line: 1305
apis:
  - protocol: rpc
    path: "vkey::install"
    description:
      zh: >
          幂等安装：找到目标模块并把它导入表里的 `GetAsyncKeyState` 换掉。
          
      en: >
          Idempotent install: locate the target module and swap its imported `GetAsyncKeyState`.
          
  - protocol: rpc
    path: "vkey::press_all"
    description:
      zh: >
          一次按键动作（可含修饰键 + 主键），按"动作"计一次数。
          
      en: >
          One key action (may include modifiers plus a main key), counted once per action.
          
  - protocol: rpc
    path: "hook_get_async_key_state"
    description:
      zh: >
          替换进 EFMI 导入表的函数：我们伪造的键返回按下状态，其余的键原样转给真实的 `GetAsyncKeyState`。
          
      en: >
          The function swapped into EFMI's import table: forged keys report as held, everything else is forwarded to the real `GetAsyncKeyState`.
          
deps:
  - kind: reference
    to: modecontroller.backend.selfcheck.panel
    label: {zh: "自检用同一份导入表判据", en: "Same probe as the self-check"}
---
