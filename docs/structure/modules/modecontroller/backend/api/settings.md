---
uid: b1d0c007
id: modecontroller.backend.api.settings
parent: modecontroller.backend.api
tags: [api, settings]
name: {zh: "设置与开关", en: "Settings & Switches"}
description:
  zh: >
      设置页碰到的所有开关与路径：热键接管、DLSS5 / 组件 addon / Poser 开关、Mod 备份开关与目录选择、下载加速设置、路径选择器，以及各种“在资源管理器里打开”。
      
  en: >
      Every toggle and path the settings page touches: hotkey takeover, DLSS5 / component add-on / Poser switches, mod-backup switch and directory picker, download acceleration settings, path choosers and the open-in-explorer entries.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.298Z"
fingerprint: f4f737f3126ceb30b7fe4eb77e658a2d448e8b85926c1be3e9f378bba509a468
source:
  - path: "endfieldmodcontroller/api.py"
    line: 346
    end_line: 778
  - path: "endfieldmodcontroller/api.py"
    line: 1429
    end_line: 2013
  - path: "endfieldmodcontroller/api.py"
    line: 2397
    end_line: 3946
apis:
  - protocol: rpc
    path: "set_hotkey_takeover"
    description:
      zh: >
          开关“整合 Mod 快捷键”（有闸门：证不了面板已部署就拒绍锁键）。
          
      en: >
          Turn hotkey takeover on/off (gated: refuses to lock keys when the panel cannot be proven deployed).
          
  - protocol: rpc
    path: "set_component_addon"
    description:
      zh: >
          开关一个可选 addon 组件（显卡不支持 DLSS5 时会被拒并说明）。
          
      en: >
          Enable/disable an optional add-on component (rejects DLSS5 on unsupported GPUs).
          
  - protocol: rpc
    path: "set_mod_backup_dir"
    description:
      zh: >
          选择/清空 Mod 备份目录（会拒绝与 Mod 库重叠的位置）。
          
      en: >
          Pick / clear the mod backup directory (rejects a directory overlapping the library).
          
  - protocol: rpc
    path: "get_download_settings"
    description:
      zh: >
          读写下载加速设置。
          
      en: >
          Read / write download acceleration settings.
          
  - protocol: rpc
    path: "choose_path"
    description:
      zh: >
          系统目录选择器，所有要填路径的地方都用它。
          
      en: >
          Native folder picker, used wherever a path is configured.
          
  - protocol: rpc
    path: "open_path"
    description:
      zh: >
          在资源管理器里打开一个路径（限白名单根目录，拒绍直接执行文件）。
          
      en: >
          Open a path in Explorer (whitelisted roots, refuses to execute files).
          
deps:
  - kind: call
    to: modecontroller.backend.config
    label: {zh: "落盘配置", en: "Persists config"}
---
