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
      
revision: 5d0b7afdfa484162eedc2a76fff664d094efa131
updated_at: "2026-10-12T15:24:16.900Z"
fingerprint: df6529aad619b8de2193fd4ef8998f5e445ff793745c19f17f97fb0ce6e4b122
source:
  - path: "scripts/snapshot.py"
    line: 2
    end_line: 318
apis:
  - protocol: rpc
    path: "scripts.snapshot"
    description:
      zh: >
          把 git 状态、exe/addon 哈希、数据根关键文件与游戏目录完整清单记进一个工作区之外的时间戳目录。
          
      en: >
          Record git state, exe/addon hashes, the data root's key files and a full game-folder inventory into a timestamped folder outside the workspace.
          
---
