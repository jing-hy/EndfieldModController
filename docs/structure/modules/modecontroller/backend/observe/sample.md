---
uid: b1d0f00d
id: modecontroller.backend.observe.sample
parent: modecontroller.backend.observe
tags: [sample]
name: {zh: "运行时采样", en: "Runtime Sampling"}
description:
  zh: >
      在游戏跑着时低成本采样：工作集、线程数、非系统路径的已加载模块 —— 按时间线追加，好让后来的崩溃包看到“崩之前变了什么”，而不只是最终状态。
      
  en: >
      Sample the running game cheaply: working set, thread count, loaded modules outside system paths — appended as a timeline so a later crash bundle shows what changed before it, not just the final state.
      
revision: 8665ab0f899233347bb25a1f29f1a8e010befe64
updated_at: "2026-10-18T12:50:41.429Z"
fingerprint: a628b0dc21b0eea3eef6dee66ac035eb7614a1e88c12b4fdaf8db892ce38c6ec
source:
  - path: "endfieldmodcontroller/watchsample.py"
    line: 98
    end_line: 302
apis:
  - protocol: rpc
    path: "sample"
    description:
      zh: >
          对运行中的游戏做一次低成本采样：工作集、线程数、非系统模块。
          
      en: >
          Cheap runtime sample of the running game: working set, thread count, non-system modules.
          
  - protocol: rpc
    path: "summarise"
    description:
      zh: >
          把采样时间线变成崩溃报告里展示的那几行。
          
      en: >
          Turn the sampled timeline into the lines a crash report shows.
          
---
