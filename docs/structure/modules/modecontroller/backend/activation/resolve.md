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
      
revision: 7d3751c3a9deb8ef56ad274079af27fe51475597
updated_at: "2026-11-28T06:33:44.862Z"
fingerprint: 518927801cbd3245ddd89278a488a10fa2a7d4b3131547488d0d8c1adac05c59
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 99
    end_line: 174
  - path: "endfieldmodcontroller/activation.py"
    line: 278
    end_line: 522
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
