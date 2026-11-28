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
      
revision: fc554f9d7ee000bfbf7fb07d55f223390dff7a4e
updated_at: "2026-11-28T14:59:05.736Z"
fingerprint: b6cbec448155bcff8bec81042a89a2e3f4b10bcd33d3d3bd295314fed852276c
source:
  - path: "endfieldmodcontroller/injector.py"
    line: 31
    end_line: 96
  - path: "endfieldmodcontroller/injector.py"
    line: 95
    end_line: 192
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
