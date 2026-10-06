---
uid: b1d10002
id: modecontroller.backend.game.clean-restore
parent: modecontroller.backend.game
tags: [clean]
name: {zh: "备份净化与还原", en: "Backup, Clean & Restore"}
description:
  zh: >
      把游戏目录弄干净但一个都不丢：把第三方文件移进带时间戳的备份（**从不删除**）、把系统原版模块另存以便放回、列出备份、并支持按需还原。
      
  en: >
      Make the game folder clean again without losing anything: move third-party files into a stamped backup (never delete), keep the original system module aside so it can be put back, list backups, and restore a backup on demand.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.964Z"
fingerprint: f5028d650b3eea84783d0aac28bd4537dd3c82208e4cc4b7d48a7c0547969586
source:
  - path: "endfieldmodcontroller/game_clean.py"
    line: 429
    end_line: 895
  - path: "endfieldmodcontroller/game_clean.py"
    line: 475
    end_line: 1979
apis:
  - protocol: rpc
    path: "game_clean.backup_and_clean"
    description:
      zh: >
          把第三方文件移进带时间戳的备份（**从不删除**），并把真正的系统模块补回去。
          
      en: >
          Move third-party files into a timestamped backup (never delete) and put the real system modules back.
          
  - protocol: rpc
    path: "game_clean.restore"
    description:
      zh: >
          按清单还原备份，逐文件进行，并做路径越界校验。
          
      en: >
          Restore a backup by its manifest, one file at a time, with path-escape checks.
          
  - protocol: rpc
    path: "game_clean.quarantine_injector"
    description:
      zh: >
          把抢了 DLSS5 hook 的第三方 NGX 注入器（如 OptiScaler）**备份后移走** —— 可还原。
          
      en: >
          Quarantine a third-party NGX injector (e.g. OptiScaler) that is stealing DLSS5's hook — backed up and reversible.
          
deps:
  - kind: call
    to: modecontroller.backend.game.clean-audit
    label: {zh: "先审计", en: "Audits first"}
---
