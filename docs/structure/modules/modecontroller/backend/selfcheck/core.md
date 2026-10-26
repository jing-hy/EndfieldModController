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
      
revision: 4c20d3f6f853c184a5b5f45604e8a406d2d05d30
updated_at: "2026-10-26T13:41:19.221Z"
fingerprint: 494f5a6fe73f7e214b3ac18d664c8c3baf244894df82fa44c3809b74db7dac7e
source:
  - path: "endfieldmodcontroller/initialize.py"
    line: 312
    end_line: 1385
  - path: "endfieldmodcontroller/initialize.py"
    line: 5101
    end_line: 8441
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
