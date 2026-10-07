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
      
revision: 4c6f9c516371a0e037c4a033a394270fa154178d
updated_at: "2026-10-07T05:13:35.527Z"
fingerprint: 1f6266d1aca64db85ba254b5d330cbcb42f96ca5d851b23e2503ed0d3713ff92
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 127
    end_line: 2662
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1066
    end_line: 2742
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1011
    end_line: 2662
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
