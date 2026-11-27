---
uid: b1d1400a
id: modecontroller.scripts.push
parent: modecontroller.scripts
tags: [git]
name: {zh: "快照与推送", en: "Snapshot & Push"}
description:
  zh: >
      安全地推 main：先快照环境（git 状态、测试数据根、游戏目录清单），再用 token 推送 —— 快照失败就不推。
      
  en: >
      Push main safely: snapshot the environment first (git state, test data root, game folder inventory), then push with the token — and refuse to push if the snapshot failed.
      
revision: 937fe82bf051035b1e0468313d39b1279ef6f60a
updated_at: "2026-11-27T14:47:15.290Z"
fingerprint: 413abf4358c1eebed1b0288e49f1ac5e2ef54c686335e803e9a8088189f88c7d
source:
  - path: "scripts/push.py"
    line: 2
    end_line: 793
apis:
  - protocol: rpc
    path: "scripts.push"
    description:
      zh: >
          先快照环境，再推 main —— **快照失败就不推**。
          
      en: >
          Snapshot the environment first, then push main — and refuse to push at all if the snapshot failed.
          
---
