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
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.965Z"
fingerprint: a7ab21a9123e742c930650597522dc692e25212788b1c0b2db34442be6abc425
source:
  - path: "endfieldmodcontroller/game_clean.py"
  - path: "endfieldmodcontroller/poser.py"
  - path: "endfieldmodcontroller/secondary_motion.py"
---
