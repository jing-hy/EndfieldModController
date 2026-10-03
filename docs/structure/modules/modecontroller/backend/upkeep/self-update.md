---
uid: b1d1100b
id: modecontroller.backend.upkeep.self-update
parent: modecontroller.backend.upkeep
tags: [update]
name: {zh: "程序自更新", en: "Program Self-Update"}
description:
  zh: >
      把正在跑的程序换成新版：查 release、挑出对的 exe 资产、下载并体检、然后写一个“等我们退出再替换”的辅助批处理来完成更换 —— 全程序最容易出错的一个操作。
      
  en: >
      Replace the running program with a newer one: check the release, rank and pick the right exe asset, download and sanity-check it, then apply by writing a helper batch script that waits for us to exit — the single most fragile operation in the program.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.320Z"
fingerprint: 83197284e22ac0cd985f0828273f68ef02444f9852586a7e08959d156aba7456
source:
  - path: "endfieldmodcontroller/selfupdate.py"
    line: 44
    end_line: 115
  - path: "endfieldmodcontroller/selfupdate.py"
    line: 115
    end_line: 403
  - path: "endfieldmodcontroller/selfupdate.py"
    line: 403
    end_line: 600
apis:
  - protocol: rpc
    path: "selfupdate.check_update"
    description:
      zh: >
          去 Release 查程序自己有没有新版。
          
      en: >
          Check the release for a newer version of the program itself.
          
  - protocol: rpc
    path: "selfupdate.download_update"
    description:
      zh: >
          下载新 exe，校验摘要（没有摘要时校验 PE 头）。
          
      en: >
          Download the new exe, verifying digest (and PE header when there is no digest).
          
  - protocol: rpc
    path: "selfupdate.apply_update"
    description:
      zh: >
          靠纯 ASCII 的 VBS 辅助脚本替换正在跑的 exe —— 脚本必须**活得比新实例久**（PyInstaller onefile 的父进程校验）。
          
      en: >
          Replace the running exe via a pure-ASCII VBS helper that must outlive the new instance (PyInstaller onefile parent check).
          
  - protocol: rpc
    path: "selfupdate.pending_payload"
    description:
      zh: >
          有没有已下载还在等的更新，它是否仍比我们新。
          
      en: >
          Is there a downloaded update still waiting, and is it still newer than us.
          
deps:
  - kind: call
    to: modecontroller.backend.components.github
    label: {zh: "用 GitHub 访问", en: "Uses GitHub access"}
---
