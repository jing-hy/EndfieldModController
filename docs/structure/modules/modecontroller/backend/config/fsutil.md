---
uid: b1d12007
id: modecontroller.backend.config.fsutil
parent: modecontroller.backend.config
tags: [io, safety]
name: {zh: "原子写与库护栏", en: "Atomic IO & Library Guard"}
description:
  zh: >
      磁盘安全原语：用统一方式算文件哈希、取不冲突的兄弟名、经临时文件原子写字节/文本，以及“这个目录到底能不能碰”的 Mod 库重叠冲突判定。
      
  en: >
      Disk safety primitives: hash a file the one agreed way, pick a unique sibling name, write bytes/text atomically through a temp file, and the library-overlap conflict test that decides whether an operation is allowed to touch a directory at all.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.301Z"
fingerprint: ad5b646006992f0d19f8bf761564b13670e34daf86856b5f6385342d95fe516c
source:
  - path: "endfieldmodcontroller/fsutil.py"
    line: 20
    end_line: 114
  - path: "endfieldmodcontroller/fsutil.py"
    line: 114
    end_line: 160
apis:
  - protocol: rpc
    path: "fsutil.sha256_file"
    description:
      zh: >
          用**全项目统一**的方式算文件哈希（原先六份重复实现收成了这一个）。
          
      en: >
          Hash a file the one agreed way (six duplicates were collapsed into this).
          
  - protocol: rpc
    path: "fsutil.write_text_atomic"
    description:
      zh: >
          原子写文本：临时文件 + 替换（不会写出半截配置，也不留 tmp 垃圾）。
          
      en: >
          Atomic text write via temp file + replace (no half-written configs, no tmp litter).
          
  - protocol: rpc
    path: "fsutil.library_conflict"
    description:
      zh: >
          判定“这个目标能不能碰”的唯一入口：它就是库 / 在库内 / 是库的上级。
          
      en: >
          The single judge of "is this target dangerous to touch": is it the library, inside it, or its parent.
          
---
