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
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.765Z"
fingerprint: 0b4effd72537003b0148461f7616e567148f629e4a82460128c233b36f39d210
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
