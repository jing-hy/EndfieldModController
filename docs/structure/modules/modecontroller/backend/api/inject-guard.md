---
uid: b1d0c00a
id: modecontroller.backend.api.inject-guard
parent: modecontroller.backend.api
tags: [api, safety]
name: {zh: "注入与安全模式", en: "Injection & Safe Mode"}
description:
  zh: >
      反作弊与注入安全面：进出提权安全模式、开关 d3d12 代理模式、审计/清理/还原游戏目录里的第三方文件，以及报告多开状态。
      
  en: >
      The anti-cheat / injection safety surface: enter and leave the elevated-anti-cheat safe mode, switch the d3d12 proxy mode on and off, audit / clean / restore what third-party files sit in the game folder, and report multi-instance status.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.295Z"
fingerprint: f4f737f3126ceb30b7fe4eb77e658a2d448e8b85926c1be3e9f378bba509a468
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2182
    end_line: 2869
  - path: "endfieldmodcontroller/api.py"
    line: 4551
    end_line: 6467
apis:
  - protocol: rpc
    path: "enable_anti_cheat_safe_mode"
    description:
      zh: >
          进入提权反作弊安全模式（关注入 + 清理游戏目录，可撤销）。
          
      en: >
          Enter the elevated anti-cheat safe mode (turns injections off + cleans the game folder, reversible).
          
  - protocol: rpc
    path: "restore_anti_cheat_safe_mode"
    description:
      zh: >
          退出安全模式并把之前的状态放回去。
          
      en: >
          Leave safe mode and put the previous state back.
          
  - protocol: rpc
    path: "enable_d3d12_proxy_mode"
    description:
      zh: >
          把 dxgi 换成我们的 d3d12 代理（以及换回来）。
          
      en: >
          Swap dxgi for our d3d12 proxy (and back).
          
  - protocol: rpc
    path: "game_clean_audit"
    description:
      zh: >
          审计 / 清理 / 还原游戏目录里的第三方文件。
          
      en: >
          Audit / clean / restore the third-party files sitting in the game folder.
          
  - protocol: rpc
    path: "audit_game_injections"
    description:
      zh: >
          看清游戏目录的注入并分类（我们的 / OptiScaler / 游戏自带 / 被替换的系统模块）。
          
      en: >
          Audit which injections are present, classified (ours / OptiScaler / game's own / replaced system module).
          
  - protocol: rpc
    path: "clean_game_injections"
    description:
      zh: >
          **按类**选择性停用，而不是一删了之。
          
      en: >
          Selectively disable an injection class rather than nuking everything.
          
deps:
  - kind: call
    to: modecontroller.backend.game
    label: {zh: "操作游戏目录", en: "Touches game folder"}
---
