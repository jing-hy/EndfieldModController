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
      
revision: aa44cfc4d4acf8d739688300e2e94583b312f729
updated_at: "2026-10-16T14:01:30.070Z"
fingerprint: c3e63d39474c69b633778348621d880f59bd66a0fed59b25d3fae873226f7b6d
source:
  - path: "frontend/src/lib/importMod.js"
    line: 2
    end_line: 202
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
