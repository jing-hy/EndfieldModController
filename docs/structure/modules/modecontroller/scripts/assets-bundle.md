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
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.923Z"
fingerprint: 78c604ce667961c54b43bb137749210cf9f4aaff911c3b84564173e5c0c4bbae
source:
  - path: "scripts/build_assets_bundle.py"
    line: 2
    end_line: 150
apis:
  - protocol: rpc
    path: "scripts.build_assets_bundle"
    description:
      zh: >
          把 `assets/` 打成 `assets-bundle.zip`（ZIP_STORED —— 载荷本来就是 xz，不二次压缩、字节稳定）。
          
      en: >
          Pack assets/ into assets-bundle.zip with ZIP_STORED (the payload is already xz — no double compression, stable bytes).
          
---
