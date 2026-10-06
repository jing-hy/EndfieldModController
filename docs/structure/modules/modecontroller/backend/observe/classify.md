---
uid: b1d0f002
id: modecontroller.backend.observe.classify
parent: modecontroller.backend.observe
tags: [verdict]
name: {zh: "崩溃判定", en: "Crash Verdict"}
description:
  zh: >
      把证据变成判断：只有真的上传了崩溃转储才算崩；再判它属于哪类 —— 显卡着色器编译器、Mod 资源冲突、还是其它 —— 并对照 DLSS5 插件自己写的崩溃记录，避免两条链路给出矛盾结论。
      
  en: >
      Turn evidence into a verdict: only an uploaded crash dump counts as a crash; then attribute it — GPU shader compiler, mod resource conflict, or something else — and cross-check the DLSS5 add-on's own crash record so one verdict never contradicts another.
      
revision: ec6d352f646115c51b7b413c56b5095ba5e52eeb
updated_at: "2026-10-06T05:52:00.974Z"
fingerprint: 0086ae622b1da38296f3275914dbc641863489736a2cb8c7eaccbb6c14e1f44a
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 126
    end_line: 2300
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 955
    end_line: 2380
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 900
    end_line: 2300
apis:
  - protocol: rpc
    path: "is_crash"
    description:
      zh: >
          唯一的崩溃判据：**真的上传了崩溃转储**才算崩，被捕获的异常不算。
          
      en: >
          The only crash predicate: an uploaded crash dump counts, a caught exception does not.
          
  - protocol: rpc
    path: "classify_cause"
    description:
      zh: >
          判崩溃属于哪类：显卡着色器编译器 / Mod 资源冲突 / 其它 —— 并与 DLSS5 插件自己写的记录交叉核对。
          
      en: >
          Attribute a crash: GPU shader compiler / mod resource conflict / other — cross-checked against the DLSS5 add-on's own record.
          
---
