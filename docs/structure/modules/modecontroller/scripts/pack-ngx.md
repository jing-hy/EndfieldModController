---
uid: b1d14005
id: modecontroller.scripts.pack-ngx
parent: modecontroller.scripts
tags: [assets]
name: {zh: "打包 NGX 资产", en: "Pack NGX Assets"}
description:
  zh: >
      把 NVIDIA NGX 运行时件按程序预期的目录结构摆好并记录逐文件哈希 —— 这些文件用户下不到（授权原因），只能随身带。
      
  en: >
      Pack the NVIDIA NGX runtime pieces into the tree the program expects, with the per-file hashes recorded — these files cannot be downloaded by the user, so they have to be carried.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.322Z"
fingerprint: 175707c6de10fc143417deb69d9bf6cc1cd773273b3970852828f17b61eb1bff
source:
  - path: "scripts/pack_nvngx_assets.py"
    line: 1
    end_line: 245
apis:
  - protocol: rpc
    path: "scripts.pack_nvngx_assets"
    description:
      zh: >
          按程序预期的目录结构摆好 NVIDIA NGX 运行时件，并记录逐文件哈希。
          
      en: >
          Lay out the NVIDIA NGX runtime pieces the program expects, with per-file hashes recorded.
          
---
