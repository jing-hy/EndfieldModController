---
uid: b1d10008
id: modecontroller.backend.game.safe-mode
parent: modecontroller.backend.game
tags: [safety]
name: {zh: "安全模式与代理切换", en: "Safe Mode & Proxy Swap"}
description:
  zh: >
      反作弊安全模式与代理切换：进入安全模式前先记下原状、停掉游戏目录的 ReShade 代理与全局 ReShade 应用项、把 dxgi 换成我们的 d3d12 代理，并能一字不差地恢复回去。
      
  en: >
      The anti-cheat safe mode and proxy switching: record what was on before entering safe mode, disable game ReShade proxies and the global ReShade app entry, swap dxgi for our d3d12 proxy, and put everything back exactly as it was.
      
revision: 55db4a68d2887afd4194c6e6b519ad091940608b
updated_at: "2026-11-28T14:23:15.808Z"
fingerprint: 0349ed6888285bb3f99b53390aa868f8ad657a9499de5d67c34e63214c7c3653
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 1340
    end_line: 2587
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 1525
    end_line: 2853
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 1749
    end_line: 3033
apis:
  - protocol: rpc
    path: "reshade_integration.safe_mode_active"
    description:
      zh: >
          安全模式现在激活着吗（以及它改了什么）。
          
      en: >
          Is the anti-cheat safe mode currently active (and what did it change).
          
  - protocol: rpc
    path: "reshade_integration.swap_dxgi_to_d3d12"
    description:
      zh: >
          把 `dxgi.dll` 换成我们的 d3d12 代理、并能换回来（原文件有记录）。
          
      en: >
          Swap dxgi.dll for our d3d12 proxy and back, recording the original.
          
  - protocol: rpc
    path: "reshade_integration.disable_global_reshade_for_game"
    description:
      zh: >
          只针对这个游戏停用全局 ReShade 应用项，可逆。
          
      en: >
          Disable the machine-wide ReShade entry for this game only, reversibly.
          
---
