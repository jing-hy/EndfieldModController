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
      
revision: f6f018e650111be669b39896b4a614a0d757c3a7
updated_at: "2026-11-07T04:47:38.255Z"
fingerprint: d4747ea6c02c00507de3113260fb95ed7a96c782001b24a0feb4fca2141804b4
source:
  - path: "endfieldmodcontroller/api.py"
    line: 2537
    end_line: 5086
  - path: "endfieldmodcontroller/api.py"
    line: 8833
    end_line: 15194
apis:
  - protocol: rpc
    path: "check_app_update"
    description:
      zh: >
          去 GitHub 查程序自己有没有新版。
          
      en: >
          Check GitHub for a newer release of the program itself.
          
  - protocol: rpc
    path: "start_app_update"
    description:
      zh: >
          在界面上跑完整一轮自更新：检查 → 下载 → 等用户决定何时安装。 已有别的下载任务在跑时**明确拒绝**（`busy`），不再把那个任务的进度当自更新结果。
          
      en: >
          Runs one self-update round from the UI: check, download, then wait for the user to install. Refuses with `busy` while another download runs.
          
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
