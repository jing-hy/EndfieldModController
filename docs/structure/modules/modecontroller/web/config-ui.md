---
uid: b1d1300c
id: modecontroller.web.config-ui
parent: modecontroller.web
tags: [settings]
name: {zh: "设置表单", en: "Settings Form"}
description:
  zh: >
      设置页（Vue）：六个分组 + 顶部动作区 + 运行状态 + 详细状态面板；表单项走 SettingPath / SettingSwitch / SettingSelect。
      
  en: >
      Settings page (Vue): six groups, top action row, runtime status and a detail probe panel.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.134Z"
fingerprint: 5cb5bb99d2b235e9a57e5074e45b9d13455c524cc0f629fbe1ee497f221ebc1e
source:
  - path: "frontend/src/pages/SettingsPage.vue"
    line: 2
    end_line: 1854
apis:
  - protocol: rpc
    path: "web.refreshFromState"
    description:
      zh: >
          把后端状态灌进表单，并重渲所有依赖它的地方（含只读的「主路径」）。
          
      en: >
          Pull the whole backend state into the form and re-render everything that depends on it (including the read-only main path).
          
  - protocol: rpc
    path: "web.refreshPaths"
    description:
      zh: >
          刷新设置页的路径字段与推导出来的路径标签。
          
      en: >
          Refresh the settings page path fields and the derived path labels.
          
  - protocol: rpc
    path: "web.saveConfig"
    description:
      zh: >
          保存设置 —— 特殊字段（如备份目录）走各自带校验的 API；留空的路径后端会按默认值回填。
          
      en: >
          Save settings — special fields (like the backup directory) go through their own validated API; blank paths are refilled by the backend.
          
  - protocol: rpc
    path: "web.asStoredPath"
    description:
      zh: >
          把自动探测到的路径写成“数据根内→相对 / 根外→绝对”再存。
          
      en: >
          Store an auto-detected path as relative inside the data root, absolute outside.
          
deps:
  - kind: call
    to: modecontroller.backend.api.settings
    label: {zh: "保存配置", en: "Saves config"}
---
