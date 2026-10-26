---
uid: b1d0b002
id: modecontroller.backend.activation.plan-deps
parent: modecontroller.backend.activation
tags: [deps]
name: {zh: "依赖规划与去重", en: "Dependency Planning"}
description:
  zh: >
      给每个需要的依赖只挑一份：内部 _deps 与外部哪侧优先、同侧多份只留最后安装的、跳过已知有害的依赖，并把选中结果与被屏蔽的候选（带原因）都记下来。
      
  en: >
      Pick exactly one copy of each needed dependency: internal (_deps) vs external preference, only-one-instance rule from the author's warning, keep the last installed within a side, skip known-bad dependencies, and record both the choices and what was blocked with a reason.
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.190Z"
fingerprint: 0941030711c371eeb8676753e085b97460037e315cb1aa918669e97450882c58
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 117
    end_line: 195
  - path: "endfieldmodcontroller/activation.py"
    line: 138
    end_line: 403
apis:
  - protocol: rpc
    path: "plan_dependencies"
    description:
      zh: >
          给每个需要的依赖只挑一份（内部/外部哪侧优先、同侧取最后安装的、跳过已知有害的）。
          
      en: >
          Choose exactly one copy of each needed dependency (internal vs external, latest within a side, skip known-bad).
          
  - protocol: rpc
    path: "dependency_note"
    description:
      zh: >
          把规划结果翻成运维读的三行日志：依赖启用 / 去重屏蔽及原因 / 缺失。
          
      en: >
          Turn the plan into the three log lines operators read: enabled / deduped-and-why / missing.
          
deps:
  - kind: reference
    to: modecontroller.backend.library.deps-detect
    label: {zh: "用依赖 key 判据", en: "Uses dependency keys"}
---
