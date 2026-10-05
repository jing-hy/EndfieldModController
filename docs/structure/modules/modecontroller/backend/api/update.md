---
uid: b1d0c008
id: modecontroller.backend.api.update
parent: modecontroller.backend.api
tags: [api, update]
name: {zh: "程序自更新", en: "App Self-Update"}
description:
  zh: >
      程序自更新：有没有待更新的版本、查 GitHub、下载新 exe，然后写一个辅助脚本并重启来完成替换（全程序最容易出问题的一段）。
      
  en: >
      Self-update from the UI: is there a pending update, check GitHub, download the new exe, then apply it by writing a helper script and restarting (the trickiest part of the whole program).
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.298Z"
fingerprint: f4f737f3126ceb30b7fe4eb77e658a2d448e8b85926c1be3e9f378bba509a468
source:
  - path: "endfieldmodcontroller/api.py"
    line: 1312
    end_line: 1762
  - path: "endfieldmodcontroller/api.py"
    line: 5272
    end_line: 8072
apis:
  - protocol: rpc
    path: "check_app_update"
    description:
      zh: >
          去 GitHub 查程序自己有没有新版。
          
      en: >
          Check GitHub for a newer release of the program itself.
          
  - protocol: rpc
    path: "download_app_update"
    description:
      zh: >
          下载新 exe（进度按依赖任务的同一套机制上报）。
          
      en: >
          Download the new exe (with progress reported as a dependency task).
          
  - protocol: rpc
    path: "apply_app_update"
    description:
      zh: >
          替换正在跑的 exe 并靠辅助脚本重启。
          
      en: >
          Replace the running exe and restart via the helper script.
          
  - protocol: rpc
    path: "pending_update"
    description:
      zh: >
          有没有已下载、等着安装的更新（下次启动会再问一次）。
          
      en: >
          Is there a downloaded update waiting to be applied (asked again next boot).
          
deps:
  - kind: call
    to: modecontroller.backend.upkeep
    label: {zh: "调自更新实现", en: "Uses updater"}
---
