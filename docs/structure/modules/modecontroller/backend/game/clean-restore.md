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
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.337Z"
fingerprint: dfb6338d113b325d6c0da03dd373af50c227d49cf338a9b8b10f4341f0292874
source:
  - path: "endfieldmodcontroller/game_clean.py"
    line: 429
    end_line: 1089
  - path: "endfieldmodcontroller/game_clean.py"
    line: 475
    end_line: 2173
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
