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
      
revision: 7c36babb44091a5965ab7f0da97455ec81ad7f61
updated_at: "2026-10-07T07:30:40.230Z"
fingerprint: 900cf7a3a79656b3b45c5c09453d93f08856ae844481d18aee095f601b4b7326
source:
  - path: "endfieldmodcontroller/fsutil.py"
    line: 48
    end_line: 860
  - path: "endfieldmodcontroller/fsutil.py"
    line: 361
    end_line: 1158
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
