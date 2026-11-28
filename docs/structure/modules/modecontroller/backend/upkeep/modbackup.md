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
      
revision: 710bd12535949f02967e1df525db653a98be673f
updated_at: "2026-11-28T15:37:36.800Z"
fingerprint: 1f1047fece7d9e31fbd9488032a3cb31fde66687185b73dc82760f1f8728b46d
source:
  - path: "endfieldmodcontroller/modbackup.py"
    line: 44
    end_line: 134
  - path: "endfieldmodcontroller/modbackup.py"
    line: 132
    end_line: 400
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
