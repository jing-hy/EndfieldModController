---
uid: b1d1ab05
id: modecontroller.scripts.memory-log
parent: modecontroller.scripts
tags: [scripts, docs]
name: {zh: "记忆日志导出", en: "Memory Log Export"}
description:
  zh: >
      把工作区记忆库导出成一份可读、可 diff 的开发日志 `docs/AI-记忆日志.md`（谁在什么时候为什么这么改、踩过什么坑）。由 `push.py` **每次推送前刷新并单独提交**（用户要求「每次传源码记忆都一起」→ 最终定为「不传记忆库本身，传一份类似记忆的日志」）。七张表列不一致要按实际列取；archived 与别的项目条目跳过；本机主目录路径脱敏。
      
  en: >
      Exports the workspace memory database into a readable, diffable development log (`docs/AI-记忆日志.md`): the decisions and the traps — refreshed and committed by `push.py` on every push. The binary database itself is never uploaded, and home-directory paths are scrubbed.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.355Z"
fingerprint: d6fcb4560afac4bde8ca8d57f0e41448106837c8f3b006aaf3e89f3cca1166b1
source:
  - path: "scripts/memory_log.py"
    line: 640
    end_line: 1468
apis: []
---
