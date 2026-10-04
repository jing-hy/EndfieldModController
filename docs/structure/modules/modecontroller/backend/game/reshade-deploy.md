---
uid: b1d10007
id: modecontroller.backend.game.reshade-deploy
parent: modecontroller.backend.game
tags: [reshade]
name: {zh: "ReShade 部署与卸载", en: "ReShade Deploy & Remove"}
description:
  zh: >
      把 ReShade 安全地装进去 / 拿出来：用清单记录装过的每个文件好精确卸载、原子拷贝、停掉与自己冲突的 add-on 并在之后恢复、收编用户已有的 ReShade dll，并在需要时下载官方安装包。
      
  en: >
      Put ReShade in and take it out safely: keep a manifest of every file installed so removal is exact, copy files atomically, disable add-ons that conflict and restore them later, adopt a ReShade dll the user already had, and download the official installer when asked.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.305Z"
fingerprint: e91e0c625160d3b0cb5d81abfc73c0b53876898d4bdd7e83a086c129f409b689
source:
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 674
    end_line: 987
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 400
    end_line: 512
  - path: "endfieldmodcontroller/reshade_integration.py"
    line: 902
    end_line: 1062
  - path: "endfieldmodcontroller/reshade.py"
    line: 26
    end_line: 45
apis:
  - protocol: rpc
    path: "reshade_integration.deploy_existing_reshade"
    description:
      zh: >
          按清单安装 ReShade（卸载才能精确），并先备份用户自己那份。
          
      en: >
          Install ReShade from a manifest so removal is exact, backing up a user's own ReShade first.
          
  - protocol: rpc
    path: "reshade_integration.remove_existing_reshade"
    description:
      zh: >
          只删我们装的那些，用户自己的原样不动。
          
      en: >
          Remove exactly the files we installed, leaving the user's own alone.
          
  - protocol: rpc
    path: "reshade.download_reshade"
    description:
      zh: >
          按需下载官方 ReShade 安装包。
          
      en: >
          Download the official ReShade installer on request.
          
deps:
  - kind: call
    to: modecontroller.backend.game.detect
    label: {zh: "先探测", en: "Detects first"}
---
