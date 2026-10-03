---
uid: b1d14002
id: modecontroller.scripts.exe-entry
parent: modecontroller.scripts
tags: [entry]
name: {zh: "exe 入口", en: "EXE Entry Shim"}
description:
  zh: >
      exe 自己的入口脚本：几行胶水 —— 导入包的 main() 并调用它，让打包能工作且不会把 pywebview 导入两次。
      
  en: >
      The exe's own entry script: a three-line shim that imports the package's main() and calls it, so freezing works without importing pywebview twice.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.321Z"
fingerprint: 87c6788e42b9c54687dbba40795e9ad4003d3d375e4d186f056eeea1a34b9312
source:
  - path: "scripts/exe_entry.py"
    line: 1
    end_line: 15
apis:
  - protocol: rpc
    path: "scripts.exe_entry"
    description:
      zh: >
          打包 exe 自己的入口胶水：导入包的 `main()` 并调用。
          
      en: >
          The frozen exe's own entry shim: import the package's main() and call it.
          
---
