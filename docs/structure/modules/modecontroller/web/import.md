---
uid: b1d13007
id: modecontroller.web.import
parent: modecontroller.web
tags: [import]
name: {zh: "拖放导入", en: "Drag & Drop Import"}
description:
  zh: >
      拖放导入（Vue）：分块上传 1 MB/块、提示层松开即消失、导入后按 need_confirm 给出归属提示。
      
  en: >
      Drag-and-drop import (Vue): 1 MB chunked upload, hint layer disappears on release, ownership hint after import.
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.940Z"
fingerprint: 8f2d373805429f1474b0c574f5b28c471583b76c1f17f223c95817e1a02c423a
source:
  - path: "frontend/src/lib/importMod.js"
    line: 2
    end_line: 204
apis:
  - protocol: rpc
    path: "web.importDroppedFile"
    description:
      zh: >
          读拖进来的文件、分块转 base64、带进度提示交给后端导入。
          
      en: >
          Read a dropped file, base64 it in chunks, and hand it to the backend importer with a progress hint.
          
  - protocol: rpc
    path: "web.initDragImport"
    description:
      zh: >
          整页拖放导入（只在 Mod 库页生效；**一松手提示就消失**）。
          
      en: >
          Whole-page drag & drop import (only active on the library tab; hint disappears the moment you drop).
          
deps:
  - kind: call
    to: modecontroller.backend.api.import
    label: {zh: "把压缩包送上去", en: "Sends archive up"}
---
