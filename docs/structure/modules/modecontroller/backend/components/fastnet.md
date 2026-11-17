---
uid: b1d11009
id: modecontroller.backend.components.fastnet
parent: modecontroller.backend.components
tags: [download]
name: {zh: "多线下载器", en: "Multi-Line Downloader"}
description:
  zh: >
      让大文件下载能扛住烂线路：探测候选镜像、记住哪条快哪条被封、退回慢线、从分片断点续传，并分块并行下载带速度估算。
      
  en: >
      Make big downloads survive a bad line: probe candidate mirrors, remember which one was fast and which one was blocked, fall back to a slower line, resume from partial parts, and download in parallel chunks with a speed estimate.
      
revision: 8bc32703d96b038ba06f91f7f4a5a9a7076791ac
updated_at: "2026-11-17T16:18:39.090Z"
fingerprint: 8da3616db726607dfdafd22e225381a46c2d6c15b4da19cd656a529e8e7b84f6
source:
  - path: "endfieldmodcontroller/fastnet.py"
    line: 298
    end_line: 3814
  - path: "endfieldmodcontroller/fastnet.py"
    line: 895
    end_line: 4434
  - path: "endfieldmodcontroller/fastnet.py"
    line: 2232
    end_line: 4744
apis:
  - protocol: rpc
    path: "download"
    description:
      zh: >
          分块并行下载、从分片断点续传，并做线路回退（直连 → 镜像）。
          
      en: >
          Download with parallel chunks, resume from partial parts, and line fallback (direct → mirrors).
          
  - protocol: rpc
    path: "probe"
    description:
      zh: >
          探测候选线路，并记住哪条快、哪条被封。
          
      en: >
          Probe candidate lines and remember which are fast and which are blocked.
          
  - protocol: rpc
    path: "resolve_lines"
    description:
      zh: >
          为某个 URL 解出可用线路表（带缓存）。
          
      en: >
          Resolve the usable line list for a URL (cache-aware).
          
---
