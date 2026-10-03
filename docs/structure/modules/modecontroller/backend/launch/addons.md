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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.306Z"
fingerprint: 625d41711e2451a0f8a305d04dd8a75624112aefc037c331b8863d1d6749bd2d
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 51
    end_line: 68
  - path: "endfieldmodcontroller/launcher.py"
    line: 997
    end_line: 1534
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
