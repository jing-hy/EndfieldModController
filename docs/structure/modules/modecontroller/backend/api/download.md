---
uid: b1d0c00d
id: modecontroller.backend.api.download
parent: modecontroller.backend.api
tags: [api, download, network]
name: {zh: "Mod 下载", en: "Mod Download"}
description:
  zh: >
      在 Mod 库页粘网址把 Mod 下回来：输入框收 http(s) 直链（去重），`ThreadPoolExecutor` 最多 4 个任务**并行**，每个任务内部再走 fastnet。文件先落在 `runtime\downloads\`；**能解压的复用导入链路自动解压入库**并识别角色，不能解压的留在原地并标「需手动解压」。**认得香蕉网（GameBanana）链接**：页面地址会经 apiv11 换成真实文件直链，并带出**封面图**、作者与版本；访问不上会标记任务并弹窗提示检查 VPN。下载并行、入库串行。
      
  en: >
      Paste URLs on the library page to fetch mods. Up to 4 jobs run in parallel (each through fastnet); files land in `runtime\downloads\`, extractable ones are imported like drag-and-drop, the rest are reported as "manual extraction needed". GameBanana page URLs are resolved via apiv11 into the real file URL plus cover, author and version; unreachable pops a VPN hint. Downloads parallel, importing serial.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.954Z"
fingerprint: 7b3471ad8619f55cbdf103637b82e37481ce339c2274229e0ff71dcc145b7b78
source:
  - path: "endfieldmodcontroller/api.py"
    line: 5040
    end_line: 9341
  - path: "endfieldmodcontroller/moddl.py"
    line: 1039
    end_line: 2320
apis:
  - protocol: rpc
    path: "start_mod_download"
    description:
      zh: >
          提交一批网址，起并行下载任务。
          
      en: >
          Submit a batch of URLs and start parallel download jobs.
          
  - protocol: rpc
    path: "mod_download_progress"
    description:
      zh: >
          轮询任务表：状态/百分比/消息 + 计数汇总。
          
      en: >
          Poll the job list: status/percent/message per job plus counts.
          
  - protocol: rpc
    path: "open_download_dir"
    description:
      zh: >
          打开下载临时目录。
          
      en: >
          Open the download temp dir.
          
deps:
  - kind: call
    to: modecontroller.backend.api.import
    label: {zh: "复用导入链路解压入库", en: "Reuses the import pipeline"}
---
