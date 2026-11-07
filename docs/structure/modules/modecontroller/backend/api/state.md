---
uid: b1d0c001
id: modecontroller.backend.api.state
parent: modecontroller.backend.api
tags: [api]
name: {zh: "状态与首屏", en: "State & Boot"}
description:
  zh: >
      界面开局与每次动作后要的东西：聚合状态包（配置、Mod 列表、依赖报告、首启标志、更新提示、设备文案）、应用信息，以及一次性初始化入口。
      
  en: >
      What the UI asks for on boot and after every action: the aggregated state payload (config, mods, dependency report, first-run flag, update hint, device text), app info, and the one-shot initialisation entry.
      
revision: 89ad502e368be7ee5b8c45c1a4d735e1870f43b9
updated_at: "2026-11-07T04:43:41.666Z"
fingerprint: 43275d255d70e23ea5822f87048fcf96695312ae473eb9e4d2e8649ba2981d89
source:
  - path: "endfieldmodcontroller/api.py"
    line: 391
    end_line: 887
  - path: "endfieldmodcontroller/api.py"
    line: 2486
    end_line: 5577
apis:
  - protocol: rpc
    path: "ui_ready"
    description:
      zh: >
          界面的第一个调用：返回聚合状态，并告诉加载页“后端就绪了”。
          
      en: >
          First call from the UI: reports the aggregated state and tells the splash when the backend is ready.
          
  - protocol: rpc
    path: "get_state"
    description:
      zh: >
          聚合状态包（配置、Mod 列表、依赖报告、首启标志、更新提示、设备文案）。
          
      en: >
          The aggregated state payload (config, mods, dependency report, first-run flag, update hint, device text).
          
  - protocol: rpc
    path: "get_config"
    description:
      zh: >
          读写设置表单背后的原始配置对象。
          
      en: >
          Read / write the raw config object behind the settings form.
          
  - protocol: rpc
    path: "save_config"
    description:
      zh: >
          把设置页改的配置落盘。
          
      en: >
          Persist config changes coming from the settings page.
          
---
