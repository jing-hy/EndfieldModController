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
      
revision: 83a004bf635eab9ddbc7e3aa0e1545b11a005bff
updated_at: "2026-10-18T14:16:51.085Z"
fingerprint: 6d1713ef0f25614cb6b47d25c39830bb84527b997216470116050036c6d54e71
source:
  - path: "scripts/build_assets_bundle.py"
    line: 2
    end_line: 52
apis:
  - protocol: rpc
    path: "scripts.build_assets_bundle"
    description:
      zh: >
          把 `assets/` 打成 `assets-bundle.zip`（ZIP_STORED —— 载荷本来就是 xz，不二次压缩、字节稳定）。
          
      en: >
          Pack assets/ into assets-bundle.zip with ZIP_STORED (the payload is already xz — no double compression, stable bytes).
          
---
