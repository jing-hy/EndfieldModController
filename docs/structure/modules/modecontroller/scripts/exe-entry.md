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
      
revision: 0120311d3899178b1012f04bba614b1cec30e883
updated_at: "2026-10-26T14:34:24.401Z"
fingerprint: 8c514beee3e3b37271b61afd5d784466073d39291ff5812c90f1b3c25da23960
source:
  - path: "scripts/exe_entry.py"
    line: 2
    end_line: 17
apis:
  - protocol: rpc
    path: "scripts.exe_entry"
    description:
      zh: >
          打包 exe 自己的入口胶水：导入包的 `main()` 并调用。
          
      en: >
          The frozen exe's own entry shim: import the package's main() and call it.
          
---
