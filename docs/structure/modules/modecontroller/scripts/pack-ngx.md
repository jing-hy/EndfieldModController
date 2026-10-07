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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.267Z"
fingerprint: c959e66adcc34087f9fa75e818f5deb0d673adcf8a80e0c44be523ffb18cd261
source:
  - path: "scripts/pack_nvngx_assets.py"
    line: 1
    end_line: 321
apis:
  - protocol: rpc
    path: "scripts.pack_nvngx_assets"
    description:
      zh: >
          按程序预期的目录结构摆好 NVIDIA NGX 运行时件，并记录逐文件哈希。
          
      en: >
          Lay out the NVIDIA NGX runtime pieces the program expects, with per-file hashes recorded.
          
---
