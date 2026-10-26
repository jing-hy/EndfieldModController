---
uid: b1d11001
id: modecontroller.backend.components.manifest
parent: modecontroller.backend.components
tags: [manifest]
name: {zh: "依赖清单", en: "Dependency Manifest"}
description:
  zh: >
      运行时所需第三方件的清单：依赖描述数据类（url、sha256、安装目录、类型）、读可编辑的 dependencies.json，以及根据当前选中的 Mod 算出到底缺哪几项。
      
  en: >
      The manifest of third-party pieces the runtime needs: the spec dataclass (url, sha256, install dir, kind), loading the editable dependencies.json, and deciding which of them are missing for the currently selected mods.
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.376Z"
fingerprint: 84c160868e64d8e2a3184c8ae837cd121004e95c8413e1ce98d807b2b0b4e93a
source:
  - path: "endfieldmodcontroller/dependencies.py"
    line: 54
    end_line: 102
  - path: "endfieldmodcontroller/dependencies.py"
    line: 101
    end_line: 119
  - path: "endfieldmodcontroller/dependencies.py"
    line: 833
    end_line: 1082
apis:
  - protocol: rpc
    path: "load_manifest"
    description:
      zh: >
          读可编辑的 dependencies.json，变成依赖描述对象。
          
      en: >
          Read the editable dependencies.json manifest into spec objects.
          
  - protocol: rpc
    path: "select_missing_dependencies"
    description:
      zh: >
          对当前选中的 Mod 来说，清单里还缺哪几项。
          
      en: >
          Which manifest entries are missing for the currently selected mods.
          
  - protocol: rpc
    path: "dependency_report"
    description:
      zh: >
          依赖页要渲染的那份依赖报告。
          
      en: >
          The dependency report the dependency page renders.
          
---
