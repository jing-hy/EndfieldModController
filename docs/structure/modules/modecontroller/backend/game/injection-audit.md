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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.304Z"
fingerprint: 61efb3f6cee6f0fb07be25de7cacec91b96852d3e1ce17a05bc74d2b78e5bf3e
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 1207
    end_line: 1425
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 1362
    end_line: 1626
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
