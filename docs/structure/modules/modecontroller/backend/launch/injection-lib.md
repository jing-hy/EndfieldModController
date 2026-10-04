---
uid: b1d0d002
id: modecontroller.backend.launch.injection-lib
parent: modecontroller.backend.launch
tags: [xxmi]
name: {zh: "注入库维护", en: "Injection Library"}
description:
  zh: >
      把 XXMI 的注入库维护对：确保启动器在位、把我们的 ReShade d3d12.dll 与 EFMI 的 d3d11.dll 登记为额外注入库、把导入器指向真正的游戏目录、并保持启动器配置有效 —— 就是它决定 Mod 到底加载不加载。
      
  en: >
      Keeping XXMI's injection library correct: ensure the launcher exists, register our ReShade d3d12.dll and the EFMI d3d11.dll as extra libraries, point the importer at the real game folder, and keep the launcher config valid — the piece that decides whether mods load at all.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.308Z"
fingerprint: 625d41711e2451a0f8a305d04dd8a75624112aefc037c331b8863d1d6749bd2d
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 1389
    end_line: 2163
  - path: "endfieldmodcontroller/launcher.py"
    line: 1541
    end_line: 2530
apis:
  - protocol: rpc
    path: "ensure_injections"
    description:
      zh: >
          把 XXMI 注入库弄对：先保签名密钥，再写游戏目录、导入器与两条额外注入库。
          
      en: >
          Make the XXMI injection library correct: signing key first, then game folder, importers and the two extra libraries.
          
  - protocol: rpc
    path: "configure_xxmi_extra_libraries"
    description:
      zh: >
          写 `extra_libraries` 及其签名，并**回读校验**。
          
      en: >
          Write (and re-read to verify) the extra_libraries list plus its signature.
          
  - protocol: rpc
    path: "ensure_xxmi_game_folder"
    description:
      zh: >
          把 XXMI 指向真正的游戏目录并确保 EFMI 处于启用 —— 不写这两个字段，XXMI 界面上就不会有启动按钮。
          
      en: >
          Point XXMI at the real game folder and make sure EFMI is enabled — without it the launcher shows no start button.
          
deps:
  - kind: call
    to: modecontroller.backend.launch.xxmi-signing
    label: {zh: "依赖签名密钥", en: "Needs signing key"}
---
