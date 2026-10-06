---
uid: 4c8be1d7
id: modecontroller.backend.config.data-root
parent: modecontroller.backend.config
tags: [config, paths, self-heal]
name: {zh: "数据根自愈", en: "Data-root Self-healing"}
description:
  zh: >
      让配置里的路径**跟着程序目录走**：记住上次的运行目录（data_root），加载时把落在旧数据根下的绝对路径自动改回相对路径（老配置无记录时用保守启发式：路径已不存在或只剩空壳、且疑似旧根已不在用）；`store_path()` 给“写配置前”统一归一化（根内→相对、根外→绝对）；`normalize_blank_paths()` 让设置页的“留空 = 自动”真的成立（空串会被解析成数据根本身）；`ensure_dirs()` 不再在数据根之外的历史残留位置凭空建目录。修的是群反馈「我把主路径改了文件名，然后他没识别出来」「又重新给我新建了一个空白文件」。
      
  en: >
      Makes configured paths follow the program directory: remembers the previous data root, rewrites absolute paths that lived under an old root back to relative ones on load (with a conservative heuristic when there is no record: missing or empty-shell old root), normalizes every program-derived path before it is stored, makes "leave blank = automatic" actually work, and stops creating directories outside the current data root.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.960Z"
fingerprint: dd1c269b3f8961b69a40bdbc2831031ec5d4740aa1e29b68e8ea0d9049452661
source:
  - path: "endfieldmodcontroller/config.py"
    line: 156
    end_line: 390
  - path: "endfieldmodcontroller/config.py"
    line: 1090
    end_line: 1388
apis:
  - protocol: rpc
    path: "config.store_path"
    description:
      zh: >
          写配置前归一化路径：落在数据根里的存相对路径，外面的原样保留。
          
      en: >
          Normalize a path before storing it: relative inside the data root, untouched outside.
          
  - protocol: rpc
    path: "config.normalize_blank_paths"
    description:
      zh: >
          把“留空”的路径字段按默认值回填（空串会被解析成数据根本身）。
          
      en: >
          Refill blank path fields with their defaults (an empty string resolves to the data root itself).
          
  - protocol: rpc
    path: "config.ensure_dirs"
    description:
      zh: >
          建运行目录，但绝不在数据根之外的历史残留位置凭空创建。
          
      en: >
          Create runtime directories, never resurrecting stale locations outside the data root.
          
  - protocol: rpc
    path: "config._relocate_stale_paths"
    description:
      zh: >
          加载时把旧数据根的绝对路径改回相对路径（数据根改名/搬家后的自愈核心）。
          
      en: >
          On load, rewrite absolute paths of an old data root back to relative ones.
          
---
