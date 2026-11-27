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
      
revision: 4467eb0705c4b5e7557d2c9d18f21d53778bd2de
updated_at: "2026-11-27T14:08:48.093Z"
fingerprint: 4dca650760705964c0f63d983785228c3445001d293ae7c2bbb9ea69ccf33805
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 143
    end_line: 3202
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1082
    end_line: 3282
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1027
    end_line: 3202
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
