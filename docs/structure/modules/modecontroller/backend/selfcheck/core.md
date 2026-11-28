---
uid: b1d0e001
id: modecontroller.backend.selfcheck.core
parent: modecontroller.backend.selfcheck
tags: [selfcheck]
name: {zh: "自检编排", en: "Check Orchestration"}
description:
  zh: >
      自检的主干：Report 模型（每项带 ok / fixed / manual 与一份动作清单）、按固定顺序跑的 ensure_all 入口，以及“修复复用同一条链路”的原则 —— 两个按钮永不走叉。
      
  en: >
      The spine of the self-check: the Report model (ok / fixed / manual per item plus an action list), the ordered ensure_all entry that every check hangs off, and the rule that repair re-runs exactly the same chain so the two buttons never drift apart.
      
revision: acc360d0a14c16ea7116b9922b7383553e40a3a3
updated_at: "2026-11-28T16:11:18.916Z"
fingerprint: 76b2f761d9ea49316814f86ba891173986a92c8dae86ee0749287163f8a88d4a
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 313
    end_line: 1387
  - path: "endfieldmodcontroller/initialize.py"
    line: 5096
    end_line: 8431
apis:
  - protocol: rpc
    path: "initialize.ensure_all"
    description:
      zh: >
          按固定顺序跑完所有启动检查，返回汇总报告。
          
      en: >
          Run every startup check in order and return the aggregate report.
          
  - protocol: rpc
    path: "initialize.Report"
    description:
      zh: >
          每项检查写入的结果模型（ok / fixed / manual / message + 动作清单）。
          
      en: >
          The per-item result model every check writes into (ok / fixed / manual / message + actions).
          
---
