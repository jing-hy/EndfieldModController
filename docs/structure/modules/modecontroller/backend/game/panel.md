---
uid: b1d10005
id: modecontroller.backend.game.panel
parent: modecontroller.backend.game
tags: [panel]
name: {zh: "控制器面板部署", en: "Controller Panel Deploy"}
description:
  zh: >
      我们自己的游戏内面板：addon 二进制在哪、ReShade 实际会扫哪几个目录、面板到底能不能用、部署与清理面板、装它的中文字体，以及退役旧版面板残留。⚠️ 2026-10-02 起面板**不再锁 Mod 热键** —— 它改成直接发每个 Mod 自己的**原键**（见 `modecontroller.addon.vkey-inject`），所以 `panel_info.txt` 里的 `takeover` 现在只表示"原键是否真被锁住"、恒为 0（面板据此不再误报"原键被锁、面板按键不会生效"）。
      
  en: >
      Our own in-game panel: where the add-on binary lives, which directories ReShade actually scans for add-ons, whether the panel can work at all, deploying / cleaning up the panel, installing its CJK font, retiring legacy copies. NOTE — since 2026-10-02 the panel no longer locks mod hotkeys: it sends each mod's **own original key** (see `modecontroller.addon.vkey-inject`), so `panel_info.txt`'s `takeover` field now means "are the original keys really locked" and stays 0.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.339Z"
fingerprint: 579c0bf450b6000c75e0f9ae57af2aecd763af15c3e87277dba4b37d6f1743a6
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 55
    end_line: 311
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 220
    end_line: 1252
apis:
  - protocol: rpc
    path: "reshade_integration.deploy_panel"
    description:
      zh: >
          把我们自己的游戏内面板 add-on 部署到 **ReShade 真的会扫**的那个目录。
          
      en: >
          Deploy our in-game panel add-on into the directory ReShade actually scans.
          
  - protocol: rpc
    path: "reshade_integration.panel_status"
    description:
      zh: >
          面板接管成功与否，它在哪，字体装了没。
          
      en: >
          Whether the panel took over, plus where it lives and whether its font is installed.
          
  - protocol: rpc
    path: "reshade_integration.cleanup_legacy_panels"
    description:
      zh: >
          退役旧版面板残留（否则会被加载两次）。
          
      en: >
          Retire legacy panel copies that would otherwise load twice.
          
---
