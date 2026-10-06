---
uid: b1d1100a
id: modecontroller.backend.upkeep.component-updates
parent: modecontroller.backend.upkeep
tags: [update]
name: {zh: "组件更新", en: "Component Updates"}
description:
  zh: >
      第三方件的版本账：读文件的版本资源、把已装版本与上游比、报告哪些组件有更新，并跑逐组件更新（ReShade 底座、乳摇物理、Poser）。
      
  en: >
      Version bookkeeping for the third-party pieces: read a file's version resource, compare installed versions against upstream, report which components have updates, and run the per-component updaters (ReShade base, jiggle physics, Poser).
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.983Z"
fingerprint: 84aca681bcbc26d1fe285dcbb12495899f375a1bd86a3af49187b470ea30c80c
source:
  - path: "endfieldmodcontroller/updates.py"
    line: 45
    end_line: 135
  - path: "endfieldmodcontroller/updates.py"
    line: 171
    end_line: 413
  - path: "endfieldmodcontroller/updates.py"
    line: 337
    end_line: 776
apis:
  - protocol: rpc
    path: "updates.file_version"
    description:
      zh: >
          读文件的版本资源（比较组件版本的**正确**方法 —— 不是 SizeOfImage）。
          
      en: >
          Read a file's version resource (the honest way to compare component versions — not SizeOfImage).
          
  - protocol: rpc
    path: "updates.check_updates"
    description:
      zh: >
          报告哪些第三方组件有更新的上游版本。
          
      en: >
          Report which third-party components have a newer upstream version.
          
  - protocol: rpc
    path: "updates.update_secondary_motion"
    description:
      zh: >
          更新单个组件（ReShade 底座 / 乳摇 / Poser）。
          
      en: >
          Update one component (ReShade base / jiggle physics / Poser).
          
deps:
  - kind: call
    to: modecontroller.backend.components.github
    label: {zh: "用 GitHub 访问", en: "Uses GitHub access"}
---
