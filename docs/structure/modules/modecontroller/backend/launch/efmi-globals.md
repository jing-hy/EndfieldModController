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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.238Z"
fingerprint: e6caf67402aa640892ab0f595aed44045002c053eb58f71cc2467be001d1956a
source:
  - path: "endfieldmodcontroller/launcher.py"
    line: 4219
    end_line: 6685
  - path: "endfieldmodcontroller/launcher.py"
    line: 4312
    end_line: 6856
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
