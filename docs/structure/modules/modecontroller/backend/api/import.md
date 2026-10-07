---
uid: b1d0c003
id: modecontroller.backend.api.import
parent: modecontroller.backend.api
tags: [api, import]
name: {zh: "压缩包导入", en: "Archive Import"}
description:
  zh: >
      把拖进来的压缩包弄进库：大文件分块接收（避免 WebView2 被大块 base64 卡死闪退）、小文件一次性接收、解压、收编与识别，最后回报落在哪个角色、需不需要用户确认。
      
  en: >
      Getting a dropped archive into the library: chunked receive for big files (so WebView2 does not choke on a huge base64 payload), one-shot receive for small ones, extract, adopt and identify, then report which character it landed on and whether the user must confirm.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.328Z"
fingerprint: ccf7e6da62fbc5fd85c1836a1d4e69d7b5520a7f3320ac3dddf0ca06aae773bb
source:
  - path: "endfieldmodcontroller/api.py"
    line: 6652
    end_line: 11884
apis:
  - protocol: rpc
    path: "import_mod_begin"
    description:
      zh: >
          开始分块接收压缩包（大包一次性传会把 WebView2 卡死/闪退）。
          
      en: >
          Start a chunked archive upload (big zips would kill WebView2 in one payload).
          
  - protocol: rpc
    path: "import_mod_chunk"
    description:
      zh: >
          接收上传中的一个分片。
          
      en: >
          Receive one chunk of the archive being uploaded.
          
  - protocol: rpc
    path: "import_mod_finish"
    description:
      zh: >
          收尾：解压、收编、识别角色，并回报需不需要用户确认归属。
          
      en: >
          Finish the upload: extract, adopt, identify the character, report whether the user must confirm.
          
  - protocol: rpc
    path: "import_mod_archive"
    description:
      zh: >
          小压缩包的一次性导入（为兼容保留）。
          
      en: >
          One-shot import for small archives (kept for compatibility).
          
  - protocol: rpc
    path: "import_manual_mods"
    description:
      zh: >
          收编用户丢进游戏 Mods 目录的 Mod。
          
      en: >
          Adopt mods the user dropped into the game's Mods folder.
          
deps:
  - kind: call
    to: modecontroller.backend.activation.manual-import
    label: {zh: "收编进库", en: "Adopts into library"}
---
