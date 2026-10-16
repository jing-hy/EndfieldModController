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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.057Z"
fingerprint: 17f0839d8e2915aeba62895b4ec76220c10636c6dae085f356f89fae471bbc61
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
