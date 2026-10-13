---
uid: b1d0d005
id: modecontroller.backend.launch.addons
parent: modecontroller.backend.launch
tags: [addon]
name: {zh: "面板与喂帧 add-on", en: "Panel & Feed Add-ons"}
description:
  zh: >
      随 ReShade 载荷走的 addon：我们的统一热键面板与 DLSS5 喂帧组件 —— 装、开关、报状态；其中喂帧那个在游戏自带 DLSS 时必须自动停用。
      
  en: >
      The add-ons that ride along with the ReShade payload: our unified hotkey panel and the DLSS5 feed add-on — install, enable/disable, and report status; the feed one must switch itself off when the game already does DLSS natively.
      
revision: d6153bf31b870c1ccd2e00dac49af51793b5267a
updated_at: "2026-10-13T16:02:57.649Z"
fingerprint: 43a32b5be69efb4163acdf02f09c5677cabca0dcf913909a7a1c7457430de4c0
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 52
    end_line: 70
  - path: "endfieldmodcontroller/launcher.py"
    line: 2258
    end_line: 4770
apis:
  - protocol: rpc
    path: "set_component_addons"
    description:
      zh: >
          在 ReShade 底座 dll 旁边装/启停面板与喂帧两个 add-on。
          
      en: >
          Install / enable / disable the panel and feed add-ons beside the ReShade base dll.
          
  - protocol: rpc
    path: "set_feed_addon_enabled"
    description:
      zh: >
          游戏自带 DLSS 时把喂帧组件自动停用。
          
      en: >
          Switch the DLSS5 feed add-on off when the game already does DLSS natively.
          
  - protocol: rpc
    path: "component_addon_status"
    description:
      zh: >
          报告哪些 add-on 在位、哪些是启用状态。
          
      en: >
          Report which add-ons are present and enabled.
          
deps:
  - kind: call
    to: modecontroller.backend.launch.dlss5-targets
    label: {zh: "拷进 dll 同目录", en: "Copies into dll dir"}
---
