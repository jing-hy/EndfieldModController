---
uid: b1d0b001
id: modecontroller.backend.activation.guard
parent: modecontroller.backend.activation
tags: [safety, guard]
name: {zh: "Mod 库安全护栏", en: "Library Safety Guard"}
description:
  zh: >
      “用户的 Mod 库一概不动”这道硬闸：当中转目录就是库、在库内部、或库的上级时，直接报错并拒绝执行 —— 因为曾经就是这种配置把一位用户的整库删光了。
      
  en: >
      The hard rule that the user's mod library is never touched: raise a guard error and refuse to stage whenever the staging directory is the library, inside it, or its parent — because that is exactly how one user's whole library got wiped.
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.505Z"
fingerprint: 1c66d0a8893ddf5663010da5c68274f9657a68639d706dc41c8a61917df95902
source:
  - path: "endfieldmodcontroller/activation.py"
    line: 78
    end_line: 143
  - path: "endfieldmodcontroller/activation.py"
    line: 776
    end_line: 1061
apis:
  - protocol: rpc
    path: "LibraryGuardError"
    description:
      zh: >
          只要某个操作会碰到用户的 Mod 库就抩这个异常；api 层把它转成界面上的「保护 Mod 库」提示。
          
      en: >
          Raised whenever an operation would touch the user's mod library; the api turns it into a 「保护 Mod 库」 dialog.
          
---
