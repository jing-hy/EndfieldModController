---
uid: b1c0b009
id: modecontroller.backend.game
parent: modecontroller.backend
tags: [game, inject]
name: {zh: "游戏目录侧集成", en: "Game-Side Integrations"}
description:
  zh: >
      所有会碰游戏目录的事：把第三方文件备份后移走（可一键还原）、通过 Poser 自带的 deploy.ps1 安装/卸载摆姿插件、注入乳摇物理 dll，以及把 ReShade（底座 dll + addon + preset）接进启动链路。
      
  en: >
      Everything that touches the game folder itself: cleaning third-party files aside with a reversible backup, installing/removing the Poser posing plugin through its own deploy.ps1, injecting the jiggle-physics dll, and glueing ReShade (base dll + addons + preset) into the launch chain.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.338Z"
fingerprint: a3118ce3491b5faab32b631dbdfd21a777214b9959391f54bda749d1e872d7cb
source:
  - path: "endfieldmodcontroller/game_clean.py"
  - path: "endfieldmodcontroller/poser.py"
  - path: "endfieldmodcontroller/secondary_motion.py"
---
