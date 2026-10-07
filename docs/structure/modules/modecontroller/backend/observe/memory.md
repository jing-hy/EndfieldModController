---
uid: b1d0f003
id: modecontroller.backend.observe.memory
parent: modecontroller.backend.observe
tags: [memory]
name: {zh: "崩溃记忆与已验证组合", en: "Crash Memory & Proven Combos"}
description:
  zh: >
      让程序不唠叨的那份记忆：“哪套组合之前崩过”、“哪套后来证明能跑”（于是撤回警告）、“哪些冲突被一次成功运行否掉”，加上当前 staged Mod 清单与启动前风险包。
      
  en: >
      The memory that keeps the program from nagging: which mod combinations crashed before, which ones later proved they run fine (so the warning is withdrawn), and which conflicts were disproved by a successful run — plus the current staged mod list and the pre-launch risk payload.
      
revision: 20521577d9cf0d2206617a54825953f305763895
updated_at: "2026-10-07T14:32:31.348Z"
fingerprint: 4bf7bb265341b41be4a347c6da397babeb121ac7387d84bd27164badca610ff7
source:
  - path: "endfieldmodcontroller/crashwatch.py"
    line: 1161
    end_line: 4456
apis:
  - protocol: rpc
    path: "crashwatch.remember_crash"
    description:
      zh: >
          记住刚才哪套组合崩了（同一组合只留最近一次，有上限）。
          
      en: >
          Remember which mod combination just crashed (kept last-per-combination, capped).
          
  - protocol: rpc
    path: "crashwatch.read_crash_memory"
    description:
      zh: >
          读回崩溃记忆。
          
      en: >
          Read back the crash memory.
          
  - protocol: rpc
    path: "crashwatch.prelaunch_risks"
    description:
      zh: >
          启动前风险包：静态冲突 + 这套组合的崩溃记忆。
          
      en: >
          The pre-launch risk payload: static conflicts + remembered crashes for this combination.
          
  - protocol: rpc
    path: "crashwatch.combo_succeeded"
    description:
      zh: >
          这一趟是否**确实跑通**（正常退出，或存活 ≥ 120 秒，且无崩溃转储）。
          
      en: >
          Did this run actually succeed (normal exit, or alive ≥ 120s, and no crash dump).
          
  - protocol: rpc
    path: "crashwatch.forget_crashes_for_combo"
    description:
      zh: >
          跑通了就把匹配的崩溃记忆**移出** —— 不再唠叨一套明明能用的组合。
          
      en: >
          A successful run withdraws the matching crash memory — no more nagging about a combination that works.
          
  - protocol: rpc
    path: "crashwatch.conflict_pair_proven"
    description:
      zh: >
          这一对是否曾经一起跑通过（是则那条静态冲突推测已经作废、不再报）。
          
      en: >
          Was this pair ever proven to run together (its static conflict verdict is therefore withdrawn).
          
deps:
  - kind: call
    to: modecontroller.backend.observe.classify
    label: {zh: "用崩溃判定", en: "Uses verdict"}
---
