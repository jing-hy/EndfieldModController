---
uid: b1d14007
id: modecontroller.scripts.release-version
parent: modecontroller.scripts
tags: [version]
name: {zh: "版本号规则核对", en: "Version Rule Check"}
description:
  zh: >
      盯住版本号规则：本地版本必须等于“最新 GitHub Release + 1”，只推源码不发 Release 时不能改号 —— 三个入口各校验一遍，它就不可能走叉。
      
  en: >
      Enforce the version rule: the local version must equal the latest GitHub Release plus one, and pushing source without publishing a Release must not bump it — checked from three entry points so it cannot drift.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.323Z"
fingerprint: 421297ba7b7494ebe7d0d583c658539690ed6e9802ee2430ede206e5fcfe8fd5
source:
  - path: "scripts/release_version.py"
    line: 1
    end_line: 278
apis:
  - protocol: rpc
    path: "scripts.release_version.check"
    description:
      zh: >
          把版本号规则变成可执行核对：本地 = 最新 GitHub Release + 1；只推源码不发 Release 时**不改号**。
          
      en: >
          The version rule, executable: local must equal latest GitHub Release + 1; pushing source alone never bumps it.
          
---
