---
uid: b1d0b003
id: modecontroller.backend.activation.resolve
parent: modecontroller.backend.activation
tags: [resolve]
name: {zh: "激活集解析", en: "Active-Set Resolution"}
description:
  zh: >
      定出最终真正会加载的那一套：筛出非依赖候选，按同角色互斥（开关关了就都留），依赖只在被引用时才激活，并产出一份含 selected / dropped / missing / blocked 的报告。
      
  en: >
      Decide the final set that will actually load: filter to non-dependency candidates, apply same-character exclusivity (or keep all when the switch is off), activate dependencies only on demand, and produce a report of selected / dropped / missing / blocked.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.952Z"
fingerprint: c738191f4d1490b9970ba92e09859bbd2d55ee2657c9ce9e29ef3ba74891baca
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 98
    end_line: 172
  - path: "endfieldmodcontroller/activation.py"
    line: 277
    end_line: 472
apis:
  - protocol: rpc
    path: "resolve_active_set"
    description:
      zh: >
          定出最终会加载的那一套：同角色互斥（可旁路）、依赖按需激活，并产出 dropped/missing/blocked 报告。
          
      en: >
          Decide the final set that will load: same-character exclusivity (bypassable), on-demand dependencies, and a report of dropped/missing/blocked.
          
  - protocol: rpc
    path: "ActivationReport"
    description:
      zh: >
          一次激活集解析的结构化结果（selected / dropped / dependencies / blocked）。
          
      en: >
          The structured result of a resolution pass (selected / dropped / dependencies / blocked).
          
deps:
  - kind: call
    to: modecontroller.backend.activation.plan-deps
    label: {zh: "规划依赖", en: "Plans dependencies"}
---
