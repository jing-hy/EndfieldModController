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
      
revision: c5e7502f33b821a8fbb9f32403d00f1d3540841b
updated_at: "2026-11-28T10:16:58.134Z"
fingerprint: 98e59651d728eb65e63362f91fc5cb24001a9f36b93386853d469be7313a9720
source:
  - path: "scripts/memory_log.py"
    line: 711
    end_line: 1610
apis: []
---
