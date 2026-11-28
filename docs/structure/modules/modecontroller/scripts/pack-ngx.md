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
      
revision: 702c5e42321f8e9b483e17ba55f39b5eed1fc548
updated_at: "2026-11-28T16:50:57.014Z"
fingerprint: 2f80e30a5e518be9950d1d23eb920badb89fcef0a165793880e6dc18350877ed
source:
  - path: "scripts/pack_nvngx_assets.py"
    line: 2
    end_line: 323
apis:
  - protocol: rpc
    path: "scripts.pack_nvngx_assets"
    description:
      zh: >
          按程序预期的目录结构摆好 NVIDIA NGX 运行时件，并记录逐文件哈希。
          
      en: >
          Lay out the NVIDIA NGX runtime pieces the program expects, with per-file hashes recorded.
          
---
