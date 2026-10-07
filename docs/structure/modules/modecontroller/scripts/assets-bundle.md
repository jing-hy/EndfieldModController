---
uid: b1d14004
id: modecontroller.scripts.assets-bundle
parent: modecontroller.scripts
tags: [assets]
name: {zh: "打包资产包", en: "Pack Assets Bundle"}
description:
  zh: >
      把必须与 exe 并排的资产打成一个可上传的压缩包（shader、DLL、喂帧 addon、字体），这样新机器不必逐个下载就能恢复一整套运行时。
      
  en: >
      Pack the assets that must sit beside the exe into one uploadable archive (shaders, DLLs, the feed add-on, fonts) so a fresh machine can restore a complete runtime without downloading each piece.
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.263Z"
fingerprint: 243cb2c9800c6a43cbfcae9ecb96c02d3007c84b32d2e9ff320f23e62d13b29f
source:
  - path: "scripts/build_assets_bundle.py"
    line: 1
    end_line: 50
apis:
  - protocol: rpc
    path: "scripts.build_assets_bundle"
    description:
      zh: >
          把 `assets/` 打成 `assets-bundle.zip`（ZIP_STORED —— 载荷本来就是 xz，不二次压缩、字节稳定）。
          
      en: >
          Pack assets/ into assets-bundle.zip with ZIP_STORED (the payload is already xz — no double compression, stable bytes).
          
---
