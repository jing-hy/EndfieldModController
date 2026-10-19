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
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.862Z"
fingerprint: 09f5e157c76c13bca84f645084de4c284fad4d0bc6f33fc352a257f9e49930dc
source:
  - path: "endfieldmodcontroller/game_clean.py"
    line: 540
    end_line: 1317
  - path: "endfieldmodcontroller/game_clean.py"
    line: 586
    end_line: 2401
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
