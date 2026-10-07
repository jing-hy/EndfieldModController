---
uid: b1d10009
id: modecontroller.backend.game.injection-audit
parent: modecontroller.backend.game
tags: [inject]
name: {zh: "游戏注入审计", en: "Game Injection Audit"}
description:
  zh: >
      看清游戏目录里被注入了什么并分类：我们的 loader 代理、OptiScaler、游戏自带的 DLSS 库、还是被替换掉的系统模块 —— 然后**按类选择性停用/恢复**，而不是一删了之。
      
  en: >
      Look at what is injected into the game folder and classify it: our loader proxy, OptiScaler, the game's own DLSS libraries, or a system module that has been replaced — then disable/restore selectively instead of nuking everything.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.234Z"
fingerprint: 579c0bf450b6000c75e0f9ae57af2aecd763af15c3e87277dba4b37d6f1743a6
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 2018
    end_line: 3199
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 2178
    end_line: 3448
apis:
  - protocol: rpc
    path: "reshade_integration.audit_game_dir_injections"
    description:
      zh: >
          列清游戏目录里被注入了什么并分类：我们的 / OptiScaler / 游戏自带 / 被替换的系统模块。
          
      en: >
          List what is injected into the game folder, classified: ours / OptiScaler / game's own / replaced system module.
          
  - protocol: rpc
    path: "reshade_integration.disable_game_dir_injections"
    description:
      zh: >
          **按类**选择性停用，而不是一删了之。
          
      en: >
          Disable one injection class selectively, rather than nuking everything.
          
  - protocol: rpc
    path: "reshade_integration.optiscaler_present"
    description:
      zh: >
          装了 OptiScaler 吗（它会截获所有 NGX 调用，能把 DLSS5 饿死）。
          
      en: >
          Is OptiScaler present (it intercepts every NGX call and can starve DLSS5).
          
  - protocol: rpc
    path: "reshade_integration.native_dlss_present"
    description:
      zh: >
          游戏自带原生 DLSS 吗（是的话我们的喂帧组件就该退位）。
          
      en: >
          Does the game ship its own native DLSS (which means our feed add-on should stand down).
          
---
