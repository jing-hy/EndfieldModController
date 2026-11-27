---
uid: b1d0d006
id: modecontroller.backend.launch.efmi-globals
parent: modecontroller.backend.launch
tags: [efmi]
name: {zh: "EFMI 全局与 include", en: "EFMI Globals & Includes"}
description:
  zh: >
      让 EFMI 框架本身能干活：声明它期待的 core 全局键、保证它的 early includes 被加载（这一项配错就是“Mod 默默不出现”）、兼容旧的 costume 段，并在需要时打开它的调试日志。
      
  en: >
      Make the EFMI framework itself work: declare the core global keys it expects, make sure its early includes are loaded (a wrong setting here means mods silently never appear), keep legacy costume sections working and turn on its debug log on request.
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.273Z"
fingerprint: a37b902f3c1838d9ab6da9f527cba86f1d48ecf61c1eb2068da6d3843143db4c
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 4266
    end_line: 6779
  - path: "endfieldmodcontroller/launcher.py"
    line: 4359
    end_line: 6950
apis:
  - protocol: rpc
    path: "ensure_efmi_library_globals"
    description:
      zh: >
          声明 EFMI 框架期待的 core 全局键（这一项配错就是“Mod 默默不出现”）。
          
      en: >
          Declare the core global keys the EFMI framework expects (a wrong setting here means mods silently never appear).
          
  - protocol: rpc
    path: "ensure_efmi_early_includes"
    description:
      zh: >
          保证 EFMI 的 early includes 真的被加载。
          
      en: >
          Make sure EFMI's early includes are actually loaded.
          
  - protocol: rpc
    path: "ensure_legacy_costume_sections"
    description:
      zh: >
          让旧式 costume 段对老 Mod 仍然生效。
          
      en: >
          Keep legacy costume sections working for older mods.
          
---
