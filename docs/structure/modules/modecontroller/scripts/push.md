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
      
revision: f975cf1217353501f422ba3582c8ac5ca1fe6a13
updated_at: "2026-10-19T13:51:34.887Z"
fingerprint: de9093bb2645710b7390a269addcd43bd949db767349b4615e100b6100760e0b
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
