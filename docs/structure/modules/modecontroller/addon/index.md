---
uid: 7a3c1f20
id: modecontroller.addon
parent: modecontroller
tags: [panel, native, reshade]
name: {zh: "游戏内面板（C++ add-on）", en: "In-game Panel (C++ add-on)"}
description:
  zh: >
      自研 ReShade add-on：把 `actions.tsv` 渲染成"**每一项就是一个按钮**"的 Mod 控制面板，并把按钮点击变成该 Mod 原键的"按下"状态（见 `modecontroller.addon.vkey-inject`）。原生代码、随 exe 打包（`assets/addon/`），由 `modecontroller.backend.game.panel` 部署进 ReShade 真正会扫的目录。
      
  en: >
      Our own ReShade add-on: renders `actions.tsv` into a mod panel where **every entry is a button**, and turns a click into "key down" for that mod's own original key (see `modecontroller.addon.vkey-inject`). Native code, shipped inside the exe (`assets/addon/`), deployed by the controller.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.950Z"
fingerprint: 8caef189e043a1494e7d522fc78b3be4f10dfe023186da714a06e9dc49eda4a2
source:
  - path: "reshade_addon/src/endfieldmodcontroller_addon.cpp"
  - path: "reshade_addon/src/vkey_inject.h"
deps:
  - kind: reference
    to: modecontroller.backend.game.panel
    label: {zh: "由控制器部署进 ReShade 目录", en: "Deployed by the controller"}
---
