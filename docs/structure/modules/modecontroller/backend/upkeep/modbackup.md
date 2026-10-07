---
uid: b1d1100d
id: modecontroller.backend.upkeep.modbackup
parent: modecontroller.backend.upkeep
tags: [backup]
name: {zh: "Mod 库备份", en: "Mod Library Backup"}
description:
  zh: >
      把 Mod 库镜像到备份目录：算出还有什么需要备份、逐个 Mod 打 zip、维护索引，并拒绝把备份目录设在库内部（重叠护栏）。
      
  en: >
      Mirror the mod library into a backup folder: decide what still needs backing up, zip each mod, keep an index, and refuse to point the backup at the library itself (overlap guard).
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.353Z"
fingerprint: e93e8aca379863186fae0ed59058f0b94354d728ea0f609d83cecd67d9a43a46
source:
  - path: "endfieldmodcontroller/modbackup.py"
    line: 43
    end_line: 132
  - path: "endfieldmodcontroller/modbackup.py"
    line: 131
    end_line: 398
apis:
  - protocol: rpc
    path: "modbackup.backup_mod"
    description:
      zh: >
          把一个 Mod 以**纯文件夹**形式拷进备份仓（从不打包），不动库。
          
      en: >
          Copy one mod into the backup repo as a plain folder (never a zip), leaving the library alone.
          
  - protocol: rpc
    path: "modbackup.backup_all"
    description:
      zh: >
          把所有还没备份过的都备一份。
          
      en: >
          Back up everything that is not backed up yet.
          
  - protocol: rpc
    path: "modbackup.status"
    description:
      zh: >
          备份仓的数量、占用、待备份清单与当前目录。
          
      en: >
          Count, size, pending list and current directory of the backup repo.
          
  - protocol: rpc
    path: "modbackup.set_backup_dir"
    description:
      zh: >
          改备份仓位置 —— 与 Mod 库重叠的位置一律拒绍。
          
      en: >
          Point the backup repo elsewhere — refusing any location that overlaps the mod library.
          
---
