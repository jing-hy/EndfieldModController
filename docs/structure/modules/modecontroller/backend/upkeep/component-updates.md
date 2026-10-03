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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.319Z"
fingerprint: 60153d868f19007bf05bb7a4ea08569549ff05ac28f2551cfe603e49ecbf6169
source:
  - path: "endfieldmodcontroller/updates.py"
    line: 43
    end_line: 133
  - path: "endfieldmodcontroller/updates.py"
    line: 166
    end_line: 339
  - path: "endfieldmodcontroller/updates.py"
    line: 312
    end_line: 614
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
