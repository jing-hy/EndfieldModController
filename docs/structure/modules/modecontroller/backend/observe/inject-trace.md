---
uid: b1d0f011
id: modecontroller.backend.observe.inject-trace
parent: modecontroller.backend.observe
tags: [diagnostics, injection]
name: {zh: "注入现场时间线", en: "Injection Timeline"}
description:
  zh: >
      在启动链的五个时机各拍一张「注入现场」照片：注入库内容与签名长度、runtime\dlss5 关键文件、游戏目录注入物、以及游戏进程里实际进了哪些模块（含「该进却没进」与「同名 loader 进了两份」两类判据）——用于把「看着注入成功、实际没进进程」与「两份 loader 撞在一起」分开。
      
  en: >
      Snapshots the injection scene at five points along the launch chain: injection-library contents and signature length, key runtime\dlss5 files, game-directory injections, and which modules actually loaded in the game process — including the two judgements that separate "looked injected but never entered the process" from "two same-named loaders colliding".
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.530Z"
fingerprint: 1c5f3f545193f7b3029ed4c02aca4cea0441ecb86fe27e6d74aacac28c1844dc
source:
  - path: "endfieldmodcontroller/injecttrace.py"
    line: 1
    end_line: 284
apis:
  - protocol: rpc
    path: "record"
    description:
      zh: >
          为启动链的某个时机拍一张注入现场照片并追加落盘（任何失败都不抛）。
          
      en: >
          Snapshot and append one injection scene for a phase of the launch chain (never raises).
          
  - protocol: rpc
    path: "render"
    description:
      zh: >
          把时间线渲染成文本，供诊断包与崩溃报告用。
          
      en: >
          Render the timeline as text for the diagnostic bundle and crash report.
          
  - protocol: rpc
    path: "read_all"
    description:
      zh: >
          读出已记录的全部快照。
          
      en: >
          Read every recorded snapshot.
          
---
