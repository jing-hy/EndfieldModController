---
uid: b1d1400b
id: modecontroller.scripts.snapshot
parent: modecontroller.scripts
tags: [snapshot]
name: {zh: "环境快照", en: "Environment Snapshot"}
description:
  zh: >
      建一个可回溯的点：把配置、运行时状态、整个 Mod 库的清单与游戏目录的哈希列表拷进带时间戳的目录 —— 出事后能说清“改动前这台机器长什么样”。
      
  en: >
      Build a rollback point: copy the config, the runtime state, the whole mod library inventory and a hash listing of the game folder into a timestamped folder, so a bad change can be traced back to what the machine looked like before.
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.323Z"
fingerprint: e5f2d424efde324834e54e61fb7376a2c54ce446368bd7e8cf27fab7760b92fd
source:
  - path: "scripts/snapshot.py"
    line: 1
    end_line: 250
apis:
  - protocol: rpc
    path: "scripts.snapshot"
    description:
      zh: >
          把 git 状态、exe/addon 哈希、数据根关键文件与游戏目录完整清单记进一个工作区之外的时间戳目录。
          
      en: >
          Record git state, exe/addon hashes, the data root's key files and a full game-folder inventory into a timestamped folder outside the workspace.
          
---
