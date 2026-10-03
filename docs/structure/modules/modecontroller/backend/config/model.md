---
uid: b1d12005
id: modecontroller.backend.config.model
parent: modecontroller.backend.config
tags: [config]
name: {zh: "配置模型", en: "Config Model"}
description:
  zh: >
      其他所有模块都读的配置对象：几十个持久字段（路径、开关、下载策略、界面状态）、带“损坏配置隔离”的安全落盘、首跑的显卡默认值，以及源码运行与打包 exe 两种形态下不同的项目根 / 资源根推导。 （“数据根改名/搬家后路径自动跟随”“写配置前归一化”“留空=自动回填”“不在数据根外凭空建目录”这四件事单独拆在 `config.data-root`。）
      
  en: >
      The configuration object everything else reads: dozens of persisted fields (paths, switches, download policy, UI state), safe save with a broken-config quarantine, first-run GPU defaults, and the project-root / resource-root resolution that differs between source run and frozen exe. (Path self-healing after the program directory is renamed/moved, path normalization before saving, blank-field refill and the "never create directories outside the data root" guard live in `config.data-root`.)
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.301Z"
fingerprint: 4c9b2749c47924fbecec4e148f639bcfd18dc8031f7dc659fdd6c5a7d906dd71
source:
  - path: "endfieldmodcontroller/config.py"
    line: 14
    end_line: 117
  - path: "endfieldmodcontroller/config.py"
    line: 285
    end_line: 935
  - path: "endfieldmodcontroller/config.py"
    line: 982
    end_line: 1064
apis:
  - protocol: rpc
    path: "config.AppConfig"
    description:
      zh: >
          唯一的配置对象：几十个持久字段，加上其他模块都依赖的路径推导。
          
      en: >
          The one configuration object: dozens of persisted fields plus the path derivation everything else depends on.
          
  - protocol: rpc
    path: "config.autofill"
    description:
      zh: >
          用内置组件补齐空白字段 —— 默认只查内嵌/相对路径（毫秒级），需要时才深扫。
          
      en: >
          Fill blank fields from built-in components — cheap by default, deep scan on request.
          
  - protocol: rpc
    path: "config.cached_detect"
    description:
      zh: >
          读缓存的探测结果 —— **故意不触发扫描**（启动才快得起来）。
          
      en: >
          Read a cached detection result — deliberately never triggers a scan (that is what keeps startup instant).
          
---
