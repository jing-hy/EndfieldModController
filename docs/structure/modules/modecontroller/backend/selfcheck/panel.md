---
uid: b1d0e006
id: modecontroller.backend.selfcheck.panel
parent: modecontroller.backend.selfcheck
tags: [hotkey]
name: {zh: "面板按键通路体检", en: "Panel Key Path Check"}
description:
  zh: >
      面板按键链路的体检（2026-10-02 换形态后重写）：① **读 EFMI `d3d11.dll` 的 PE 导入表**，确认它有 `GetAsyncKeyState` 读键入口 —— 面板就是靠接住这个入口来"按"Mod 的键的，没有它 = 所有按钮都会点了没反应（可提前查出来）；② 保留旧判据 —— ReShade / 其它 addon 若占了 `F13..F24`（旧合成协议键位）仍然照报。
      
  en: >
      Health check for the panel's key path (rewritten 2026-10-02): (1) parse the PE import table of EFMI's `d3d11.dll` to confirm it imports `GetAsyncKeyState` — the panel presses mod keys by taking over exactly that call site, so without it every button would do nothing; (2) keep the legacy check — report any ReShade/add-on that occupies `F13..F24` (the old synthetic protocol keys).
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.980Z"
fingerprint: f595776e7ad640b14c5475d2570261609ebcad7da783fbd9cbeae195391a3887
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 2663
    end_line: 5066
apis:
  - protocol: rpc
    path: "panel:hotkey_conflicts"
    description:
      zh: >
          自检项 key：① EFMI 的 d3d11.dll 有 `GetAsyncKeyState` 读键入口；② ReShade / 其它 addon 没有占用 F13..F24。
          
      en: >
          Self-check key: (1) EFMI's d3d11.dll has a `GetAsyncKeyState` polling entry; (2) no ReShade add-on occupies F13..F24.
          
  - protocol: rpc
    path: "panel:protocol_lint"
    description:
      zh: >
          读生成控制器时一起产出的 `controller.lint.txt`：非 OK = 面板协议里有会被 3DMigoto 静默跳过的行（点了会没反应）。
          
      en: >
          Reads the `controller.lint.txt` produced when the controller mod is generated: non-OK means the panel protocol has lines 3DMigoto will silently skip (buttons would do nothing).
          
---
