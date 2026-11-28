---
uid: b1d1200b
id: modecontroller.backend.config.edition
parent: modecontroller.backend.config
tags: [edition, lite, reshade]
name: {zh: "版本形态", en: "Edition Profile"}
description:
  zh: >
      Universal / Lite 两种形态的唯一定义处：Lite 下运行期关闭整条 ReShade 链路（不下载、不注入、不写文件、强制净化游戏目录），并让所有“总闸”判据走同一个函数；两版共用数据根，所以对 ReShade 配置只读。
      
  en: >
      The single source of truth for the Universal/Lite editions: Lite disables the whole ReShade chain at runtime (no downloads, no injection, no writes, forced game-dir cleaning) and routes every master-switch check through one helper; both editions share a data root, so ReShade config stays read-only in Lite.
      
revision: c5e7502f33b821a8fbb9f32403d00f1d3540841b
updated_at: "2026-11-28T10:16:58.103Z"
fingerprint: dd591fefc72f435264c087efcfccc98596e219fdaadd21d69236b31d9c465bb3
source:
  - path: "endfieldmodcontroller/edition.py"
    line: 89
    end_line: 264
apis:
  - protocol: rpc
    path: "edition.current"
    description:
      zh: >
          当前形态（full / lite）。
          
      en: >
          The current edition (full or lite).
          
  - protocol: rpc
    path: "edition.effective_reshade_disabled"
    description:
      zh: >
          本次运行是否禁用所有 ReShade（Lite 恒 True，Universal 读配置总闸）。
          
      en: >
          Whether all ReShade is disabled for this run (always true in Lite; reads the config master switch otherwise).
          
---
