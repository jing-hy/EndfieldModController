---
uid: b1d1000a
id: modecontroller.backend.game.dll-injector
parent: modecontroller.backend.game
tags: [inject]
name: {zh: "DLL 注入器", en: "DLL Injector"}
description:
  zh: >
      一个精简的 Win32 DLL 注入器：按 exe 名找进程、打开、分配并写入 dll 路径、远程建线程；另含“等进程起来再注入”的辅助函数。
      
  en: >
      A minimal Win32 DLL injector: find a process by executable name, open it, allocate and write the dll path, and create a remote thread — plus the wait-and-inject helper used when a process is still starting up.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.304Z"
fingerprint: d38e1d7dad5590a759ec00deb828081db2e3482abb4b2dfe52a30c2358451a43
source:
  - path: "endfieldmodcontroller/injector.py"
    line: 30
    end_line: 94
  - path: "endfieldmodcontroller/injector.py"
    line: 94
    end_line: 190
apis:
  - protocol: rpc
    path: "injector.inject_dll"
    description:
      zh: >
          往进程里注入一个 dll：打开、分配、写入路径、远程建线程 —— 带正确的 64 位 `argtypes`。
          
      en: >
          Inject a dll into a process: open, allocate, write the path, remote thread — with correct 64-bit argtypes.
          
  - protocol: rpc
    path: "injector.wait_and_inject"
    description:
      zh: >
          等进程出现再注入（我们自己拉起它时走这条）。
          
      en: >
          Wait for a process to appear and then inject (used when we start it ourselves).
          
---
