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
      
revision: 67a073215c2dce317e8190d381e16868baade880
updated_at: "2026-10-18T09:12:03.875Z"
fingerprint: 821268b6697936614a42127c09c8dcb4cdba902ba30d9b80e92961f315e6209b
source:
  - path: "endfieldmodcontroller/fastnet.py"
    line: 298
    end_line: 3234
  - path: "endfieldmodcontroller/fastnet.py"
    line: 697
    end_line: 3854
  - path: "endfieldmodcontroller/fastnet.py"
    line: 1942
    end_line: 4164
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
