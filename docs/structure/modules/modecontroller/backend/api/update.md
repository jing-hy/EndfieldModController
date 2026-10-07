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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.332Z"
fingerprint: ccf7e6da62fbc5fd85c1836a1d4e69d7b5520a7f3320ac3dddf0ca06aae773bb
source:
  - path: "endfieldmodcontroller/api.py"
    line: 1786
    end_line: 2840
  - path: "endfieldmodcontroller/api.py"
    line: 7321
    end_line: 12170
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
