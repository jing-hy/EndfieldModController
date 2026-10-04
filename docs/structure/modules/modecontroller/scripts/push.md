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
      
revision: 45e4d6d07cf81770c867c10f0f053a5efbf5e978
updated_at: "2026-10-03T15:48:42.323Z"
fingerprint: 1689206f8e78e0781867cf1eccc98ca2892d4557202f41d0f88a08257eb91600
source:
  - path: "scripts/push.py"
    line: 1
    end_line: 347
apis:
  - protocol: rpc
    path: "scripts.push"
    description:
      zh: >
          先快照环境，再推 main —— **快照失败就不推**。
          
      en: >
          Snapshot the environment first, then push main — and refuse to push at all if the snapshot failed.
          
---
